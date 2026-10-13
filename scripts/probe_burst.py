#!/usr/bin/env python3
"""P9: does a burst faster than the EPP's metrics refresh herd onto one pod? (#22, SIMULATED)

The EPP scores pods on scraped engine metrics, refreshed every --refresh-metrics-interval (50 ms in our
deployment, default). N requests that all reach the EPP inside one interval are scored against the same
snapshot, so they may all pick the same "least loaded" pod.

Per run, from idle (every sim pod running=0, waiting=0):
  burst    N requests to sim-pool through the gateway, fired together (asyncio.gather)
  spaced   control: the same N requests, one every --spacing s (> one refresh interval)
Requests: unique prompts (neutralise the prefix-cache scorer), ignore_eos, --max-tokens long enough
that all N overlap in both modes (sim ITL ~16 ms → 200 tokens ≈ 3.3 s > (N-1) × spacing).

Which pod served each request: the gateway access log (`endpoint=` per request, plus `duration=` to
recover the start time at the gateway), cross-checked with per-pod deltas of the sim counter
vllm:e2e_request_latency_seconds_count scraped from each pod IP before and after (works from the k3s host).
There is no response header naming the endpoint.
"""
import argparse, asyncio, collections, datetime as dt, json, pathlib, re, subprocess, time, uuid
import httpx

NS, MODEL, SIM_SELECTOR = "inference", "qwen2.5-0.5b-instruct", "app.kubernetes.io/name=vllm-sim"
COUNT_RE = re.compile(r'^vllm:e2e_request_latency_seconds_count\{[^}]*\}\s+([0-9.e+]+)', re.M)
GAUGE_RE = re.compile(r'^vllm:num_requests_(running|waiting)\{[^}]*\}\s+([0-9.e+]+)', re.M)
LOG_RE = re.compile(r'^(\S+)\s.*\sroute=inference/sim-pool\sendpoint=([0-9.]+):\d+\s.*\sduration=([0-9.]+)(ms|s|µs|us)\b')
UNIT = {"ms": 1e-3, "s": 1.0, "µs": 1e-6, "us": 1e-6}


def kubectl(*args: str) -> str:
    return subprocess.run(["kubectl", "-n", NS, *args], check=True, capture_output=True, text=True).stdout


def sim_pods() -> dict[str, str]:
    items = json.loads(kubectl("get", "pods", "-l", SIM_SELECTOR, "-o", "json"))["items"]
    return {p["status"]["podIP"]: p["metadata"]["name"] for p in items
            if p["status"].get("phase") == "Running" and not p["metadata"].get("deletionTimestamp")}


async def scrape(c: httpx.AsyncClient, ips) -> dict[str, dict]:
    out = {}
    for ip in ips:
        t = (await c.get(f"http://{ip}:8000/metrics", timeout=5)).text
        out[ip] = {"count": float(COUNT_RE.search(t).group(1)),
                   **{k: float(v) for k, v in GAUGE_RE.findall(t)}}
    return out


async def wait_idle(c, ips) -> None:
    for _ in range(240):
        s = await scrape(c, ips)
        if all(v.get("running", 0) == 0 and v.get("waiting", 0) == 0 for v in s.values()):
            return
        await asyncio.sleep(0.5)
    raise SystemExit(f"sim pods not idle after 120 s: {s}")


async def one(c: httpx.AsyncClient, a, i: int) -> dict:
    body = {"model": MODEL, "max_tokens": a.max_tokens, "ignore_eos": True,
            "messages": [{"role": "user", "content": f"burst {i} {uuid.uuid4().hex}"}]}
    t = time.perf_counter()
    try:
        r = await c.post(f"{a.gateway}/v1/chat/completions", json=body, timeout=120)
        code = r.status_code
    except httpx.HTTPError as e:
        code = type(e).__name__
    return {"i": i, "sent": t, "code": code}


async def run(c, a, mode: str, ips) -> dict:
    await wait_idle(c, ips)
    before = await scrape(c, ips)
    t_run = dt.datetime.now(dt.timezone.utc)
    start = t_run - dt.timedelta(seconds=2)              # --since-time has 1 s resolution
    if mode == "burst":
        tasks = [asyncio.create_task(one(c, a, i)) for i in range(a.n)]
    else:
        tasks = []
        for i in range(a.n):
            tasks.append(asyncio.create_task(one(c, a, i)))
            if i < a.n - 1:
                await asyncio.sleep(a.spacing)
    await asyncio.sleep(0.3)                              # all routed; none finished (≈3 s each)
    during = await scrape(c, ips)
    res = await asyncio.gather(*tasks)
    await asyncio.sleep(1)                                # let the gateway flush its log
    after = await scrape(c, ips)

    log = kubectl("logs", "deploy/inference-gateway", f"--since-time={start:%Y-%m-%dT%H:%M:%SZ}")
    picks, starts = collections.Counter(), []
    for m in (LOG_RE.match(l) for l in log.splitlines()):
        if m:
            end = dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            begun = end.timestamp() - float(m.group(3)) * UNIT[m.group(4)]
            if begun < t_run.timestamp():                 # an earlier run's request
                continue
            starts.append(begun)
            picks[m.group(2)] += 1
    sent = sorted(r["sent"] for r in res)
    return {"mode": mode, "n": a.n, "spacing_s": a.spacing if mode == "spaced" else 0,
            "codes": dict(collections.Counter(r["code"] for r in res)),
            "client_send_spread_ms": round((sent[-1] - sent[0]) * 1000, 2),
            "gateway_start_spread_ms": round((max(starts) - min(starts)) * 1000, 1) if starts else None,
            "log_picks": {ip: picks.get(ip, 0) for ip in ips},
            "log_lines": sum(picks.values()),
            "counter_delta": {ip: int(after[ip]["count"] - before[ip]["count"]) for ip in ips},
            "during": {ip: {k: during[ip].get(k) for k in ("running", "waiting")} for ip in ips}}


async def main(a) -> None:
    pods = sim_pods()
    ips = sorted(pods)
    out_dir = pathlib.Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl"
    print("SIMULATED (llm-d-inference-sim) · pods:", {ip: pods[ip] for ip in ips})
    print(f"n {a.n} · max_tokens {a.max_tokens} · spacing (control) {a.spacing} s · repeats {a.repeats}")
    modes = {"both": ["burst", "spaced"], "burst": ["burst"], "spaced": ["spaced"]}[a.mode]
    totals = {m: collections.Counter() for m in modes}
    limits = httpx.Limits(max_connections=a.n * 2, max_keepalive_connections=a.n * 2)
    async with httpx.AsyncClient(limits=limits) as c:
        for rep in range(1, a.repeats + 1):
            for mode in modes:                            # alternate, so drift hits both modes
                r = await run(c, a, mode, ips)
                r["repeat"] = rep
                with out_file.open("a") as f:
                    f.write(json.dumps(r) + "\n")
                totals[mode].update(r["log_picks"])
                agree = "agree" if r["log_picks"] == r["counter_delta"] else "DISAGREE"
                print(f"\n== {mode} #{rep} (SIMULATED)  codes {r['codes']}")
                print(f"  send spread: client {r['client_send_spread_ms']} ms, gateway {r['gateway_start_spread_ms']} ms")
                print(f"  picks (gateway log)  : {r['log_picks']}  ({r['log_lines']} lines)")
                print(f"  counter delta (pods) : {r['counter_delta']}  → {agree}")
                print(f"  running/waiting +0.3s: {r['during']}")
    print("\nTotal picks per pod (gateway log, SIMULATED):")
    for mode, t in totals.items():
        print(f"  {mode:6s}: {dict(t)}")
    print(f"raw: {out_file}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--n", type=int, default=8, help="requests per run")
    p.add_argument("--max-tokens", type=int, default=200, help="long enough that all N overlap")
    p.add_argument("--spacing", type=float, default=0.25,
                   help="s between control requests (EPP refresh-metrics-interval is 50 ms)")
    p.add_argument("--mode", choices=["both", "burst", "spaced"], default="both")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out-dir", default="benchmarks/results/probes/burst")
    asyncio.run(main(p.parse_args()))
