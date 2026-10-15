#!/usr/bin/env python3
"""P8: is the EPP's routing blind to request size? (#23). SIMULATED (vLLM simulator, scratch pool p8-pool).

Per run, two sim pods are loaded so that pod A has FEWER requests but MORE queued prefill work than pod B:
  A: --n-long   closed-loop clients sending ~--long-tokens prompts   (2 x ~3000 tokens: fills A's 2 slots)
  B: --n-short  closed-loop clients sending ~--short-tokens prompts  (3 x ~200 tokens: 2 running + 1 waiting)
Then ONE probe (unique prompt, ~--probe-tokens) goes through the gateway and we record which pod the EPP
picked (EPP debug log, keyed by x-request-id), client-side TTFT (first streamed chunk), the pods' gauges
just before the probe, and the per-scorer scores the EPP computed for it.

Load paths (--load-path):
  direct        port-forward straight to each pod (as P1): the EPP never sees the load, only the pod metrics.
  gateway-pin   through the gateway with x-session-token (session-affinity-filter in the p8-pool EPP) pinning
                each request to its pod: the EPP dispatches the load, so EPP-side in-flight accounting sees it.
--force A|B pins the probe too (counterfactual: what TTFT would the probe have had on that pod).
Roles alternate between the two physical pods each run. Each run starts behind an idle guard
(both pods running=0, waiting=0, else wait up to --idle-timeout then abort).
"""
import argparse, asyncio, base64, datetime as dt, json, pathlib, re, statistics, subprocess, sys, time, uuid
import httpx

NS = "inference"
SELECTOR = "app.kubernetes.io/name=vllm-sim-p8"
MODEL = "qwen2.5-0.5b-instruct"
GAUGE_RE = re.compile(r'^vllm:(num_requests_running|num_requests_waiting|kv_cache_usage_perc)\{[^}]*\}\s+([0-9.e+-]+)', re.M)
# Sim latency model (deploy/gateway/p8/sim-p8.yaml): prefill = overhead + per_token * prompt_tokens; decode = ITL per token.
PREFILL_OVERHEAD, PREFILL_PER_TOKEN, ITL = 0.015, 0.0024, 0.0163
CHAT_TEMPLATE_TOKENS = 5          # measured: sim counts N words + ~5 for a chat message (10 words -> 15)


def kubectl(*args: str) -> str:
    return subprocess.run(["kubectl", "-n", NS, *args], check=True, capture_output=True, text=True).stdout


def pods() -> list[dict]:
    items = json.loads(kubectl("get", "pods", "-l", SELECTOR, "-o", "json"))["items"]
    ps = [{"name": p["metadata"]["name"], "ip": p["status"]["podIP"]} for p in items if p["status"].get("phase") == "Running"]
    return sorted(ps, key=lambda p: p["ip"])


def prompt(words: int) -> str:
    return f"{uuid.uuid4().hex} " + " ".join(f"w{i}" for i in range(words))


def prefill_s(tokens: int) -> float:
    return PREFILL_OVERHEAD + PREFILL_PER_TOKEN * (tokens + CHAT_TEMPLATE_TOKENS)


def pin(pod: str) -> dict:
    # The EPP names endpoints "<pod>-rank-0" (see its debug log); the filter compares NamespacedName.String().
    return {"x-session-token": base64.b64encode(f"{NS}/{pod}-rank-0".encode()).decode()}


async def gauges(c: httpx.AsyncClient, port: int) -> dict:
    r = await c.get(f"http://127.0.0.1:{port}/metrics", timeout=5)
    return {k: float(v) for k, v in GAUGE_RE.findall(r.text)}


async def idle_guard(c, ports, timeout) -> dict:
    end = time.monotonic() + timeout
    while True:
        g = [await gauges(c, p) for p in ports]
        if all(x.get("num_requests_running", 1) == 0 and x.get("num_requests_waiting", 1) == 0 for x in g):
            return {"A": g[0], "B": g[1]}
        if time.monotonic() > end:
            sys.exit(f"idle guard: pods not idle after {timeout}s: {g}")
        await asyncio.sleep(0.5)


async def load_worker(c, url, headers, words, max_tokens, stop: asyncio.Event):
    while not stop.is_set():
        body = {"model": MODEL, "max_tokens": max_tokens, "ignore_eos": True,
                "messages": [{"role": "user", "content": prompt(words)}]}
        try:
            await c.post(url, json=body, headers=headers, timeout=120)
        except (httpx.HTTPError, asyncio.CancelledError):
            return


async def probe_request(c, a, req_id, extra: dict) -> dict:
    body = {"model": MODEL, "max_tokens": 5, "stream": True, "messages": [{"role": "user", "content": prompt(a.probe_tokens)}]}
    h = {"x-pool": "p8", "x-request-id": req_id, **extra}
    t0 = time.monotonic()
    ttft = None
    async with c.stream("POST", f"{a.gateway}/v1/chat/completions", json=body, headers=h, timeout=120) as r:
        async for line in r.aiter_lines():
            if ttft is None and line.startswith("data:") and "[DONE]" not in line:
                ttft = time.monotonic() - t0
        code = r.status_code
    return {"status": code, "ttft_s": ttft, "total_s": time.monotonic() - t0}


def epp_decision(req_id: str, since: str) -> dict:
    out = {"scores": {}, "pick": None}
    log = kubectl("logs", "deploy/p8-pool-epp", f"--since-time={since}")
    for l in log.splitlines():
        if req_id not in l:
            continue
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if d.get("x-request-id") != req_id:
            continue
        if d.get("msg") == "Calculated score":
            out["scores"].setdefault(d["plugin"].split("/")[0], {})[d["endpoint"]["name"].removesuffix("-rank-0")] = d["score"]
        elif d.get("msg", "").startswith("Completed running picker"):
            out["pick"] = d["result"]["TargetEndpoints"][0]["Endpoint"]["PodName"]
    return out


async def one_run(c, a, i, ps, ports, outf, epp_profile) -> dict:
    ai = i % 2                                 # role alternation: pod index acting as A (long-prompt pod)
    A, B = ps[ai], ps[1 - ai]
    pa, pb = ports[ai], ports[1 - ai]
    idle = await idle_guard(c, [pa, pb], a.idle_timeout)
    stop = asyncio.Event()
    gw = f"{a.gateway}/v1/chat/completions"
    tasks = []

    def target(pod, port):
        if a.load_path == "direct":
            return f"http://127.0.0.1:{port}/v1/chat/completions", {}
        return gw, {"x-pool": "p8", **pin(pod["name"])}

    ua, ha = target(A, pa)
    ub, hb = target(B, pb)
    t_load = time.monotonic()
    for _ in range(a.n_long):
        tasks.append(asyncio.create_task(load_worker(c, ua, ha, a.long_tokens, a.long_max_tokens, stop)))
    for _ in range(a.n_short):
        tasks.append(asyncio.create_task(load_worker(c, ub, hb, a.short_tokens, a.short_max_tokens, stop)))
    established = False
    while time.monotonic() - t_load < a.probe_delay + 10:        # wait for the load to be in place
        ga, gb = await gauges(c, pa), await gauges(c, pb)
        if (time.monotonic() - t_load >= a.probe_delay and ga.get("num_requests_running") == a.n_long
                and gb.get("num_requests_running", 0) >= 2):
            established = True
            break
        await asyncio.sleep(0.1)
    ga, gb = await gauges(c, pa), await gauges(c, pb)
    req_id = f"p8-{int(time.time())}-{i}-{uuid.uuid4().hex[:6]}"
    since = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    extra = pin(A["name"] if a.force == "A" else B["name"]) if a.force else {}
    delay = time.monotonic() - t_load
    res = await probe_request(c, a, req_id, extra)
    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.sleep(1.0)                                     # EPP log flush
    dec = epp_decision(req_id, since)
    pick = "A" if dec["pick"] == A["name"] else "B" if dec["pick"] == B["name"] else None

    # Prediction, computed from the sim config only (no measurement): a probe on A waits for the first long
    # request to finish (prefill + decode of max_tokens), a probe on B waits for the next short-request cycle.
    long_done = prefill_s(a.long_tokens) + a.long_max_tokens * ITL
    short_cycle = prefill_s(a.short_tokens) + a.short_max_tokens * ITL
    p_pre = prefill_s(a.probe_tokens)
    exp_A = max(long_done - delay, 0) + p_pre
    exp_B = (0 + p_pre, short_cycle + p_pre)                     # slot frees somewhere within one short cycle
    rec = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "run": i, "load_path": a.load_path, "force": a.force,
           "epp_profile": epp_profile, "A": A, "B": B, "idle_before": idle, "load_established": established,
           "probe_delay_s": round(delay, 2), "gauges_at_decision": {"A": ga, "B": gb}, "probe_id": req_id,
           "pick": pick, "epp_pick_pod": dec["pick"], "epp_scores": dec["scores"], **res,
           "expected_ttft_if_A_s": round(exp_A, 2), "expected_ttft_if_B_s": [round(x, 2) for x in exp_B]}
    outf.write(json.dumps(rec) + "\n")
    outf.flush()
    print(f"run {i}: pick={pick} ttft={res['ttft_s']:.2f}s (exp A {exp_A:.2f}s, exp B {exp_B[0]:.2f}-{exp_B[1]:.2f}s) "
          f"A={ga['num_requests_running']:.0f}r/{ga['num_requests_waiting']:.0f}w kv={ga['kv_cache_usage_perc']:.3f}  "
          f"B={gb['num_requests_running']:.0f}r/{gb['num_requests_waiting']:.0f}w kv={gb['kv_cache_usage_perc']:.3f} "
          f"established={established} scores={dec['scores']}")
    return rec


def summary(recs, label):
    ok = [r for r in recs if r["pick"] and r["ttft_s"] is not None]
    t = sorted(r["ttft_s"] for r in ok)
    picks = {k: sum(1 for r in ok if r["pick"] == k) for k in ("A", "B")}
    print(f"\n== {label}: n={len(recs)} valid={len(ok)} picks A(long pod)/B(short pod) = {picks['A']}/{picks['B']}")
    if t:
        print(f"   TTFT p50={statistics.median(t):.2f}s max={t[-1]:.2f}s min={t[0]:.2f}s")
        for k in ("A", "B"):
            tk = [r["ttft_s"] for r in ok if r["pick"] == k]
            if tk:
                print(f"   picked {k}: n={len(tk)} TTFT p50={statistics.median(tk):.2f}s max={max(tk):.2f}s")


async def main(a):
    ps = pods()
    if len(ps) != 2:
        sys.exit(f"need exactly 2 sim-p8 pods, found {ps}")
    ports = [18101, 18102]
    pfs = [subprocess.Popen(["kubectl", "-n", NS, "port-forward", f"pod/{p['name']}", f"{port}:8000"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for p, port in zip(ps, ports)]
    epp_profile = kubectl("get", "deploy", "p8-pool-epp", "-o",
                          "jsonpath={.spec.template.spec.containers[0].args}")
    epp_profile = re.search(r'/config/([\w.-]+)', epp_profile).group(1)
    out = pathlib.Path("benchmarks/results/probes/p8")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{a.label}.jsonl"
    print(f"label={a.label} epp_profile={epp_profile} load_path={a.load_path} force={a.force} -> {path}")
    try:
        async with httpx.AsyncClient() as c:
            for _ in range(50):
                try:
                    await gauges(c, ports[0]); await gauges(c, ports[1]); break
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)
            recs = []
            with path.open("w") as f:
                for i in range(a.runs):
                    recs.append(await one_run(c, a, i, ps, ports, f, epp_profile))
            summary(recs, a.label)
    finally:
        for p in pfs:
            p.terminate()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--label", required=True, help="tag for the output file, e.g. off-pin")
    p.add_argument("--runs", type=int, default=6)
    p.add_argument("--load-path", choices=["direct", "gateway-pin"], default="gateway-pin")
    p.add_argument("--force", choices=["A", "B"], help="pin the probe to the long-prompt pod (A) or short-prompt pod (B)")
    p.add_argument("--n-long", type=int, default=2)
    p.add_argument("--long-tokens", type=int, default=3000)
    p.add_argument("--long-max-tokens", type=int, default=200)
    p.add_argument("--n-short", type=int, default=3)
    p.add_argument("--short-tokens", type=int, default=200)
    p.add_argument("--short-max-tokens", type=int, default=20)
    p.add_argument("--probe-tokens", type=int, default=100)
    p.add_argument("--probe-delay", type=float, default=3.0, help="s after load start before the probe is sent")
    p.add_argument("--idle-timeout", type=float, default=90)
    asyncio.run(main(p.parse_args()))
