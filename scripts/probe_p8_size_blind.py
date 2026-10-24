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

--pool cpu: the same question on the REAL llama.cpp pool (llamacpp-pool, 2 replicas, real gateway + EPP); see main_cpu().
"""
import argparse, asyncio, base64, datetime as dt, glob, json, math, os, pathlib, random, re, statistics, subprocess, sys, time, uuid
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


# ---------------------------------------------------------------- --pool cpu: real llama.cpp behind the real gateway + EPP
# Results: benchmarks/results/probes/p8_cpu_pinned.md. Load is held per block (not restarted per probe as above: one CPU
# long prefill takes ~14 s), probes go out >= --min-gap-s apart after a seeded uniform delay in [0, --jitter-s), and the
# L/S roles swap between the two physical pods halfway (block 2), with an idle guard before each block.
# TTFT = POST -> first chunk with non-empty delta.content (stream_chat in probe_p8_t4x2.py, the repo harness definition).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from probe_p8_t4x2 import stream_chat, est_tokens  # noqa: E402

CPU_SELECTOR = "app.kubernetes.io/name=llamacpp"
CPU_PORT = 8080
CPU_EPP = "llamacpp-pool-epp"
LC_RE = re.compile(r'^llamacpp:(requests_processing|requests_deferred)(?:\{[^}]*\})?\s+([0-9.e+-]+)', re.M)
REPO = pathlib.Path(__file__).resolve().parents[1]


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def cpu_pods() -> list[dict]:
    items = json.loads(kubectl("get", "pods", "-l", CPU_SELECTOR, "-o", "json"))["items"]
    ps = [{"name": p["metadata"]["name"], "ip": p["status"]["podIP"], "uid": p["metadata"]["uid"],
           "qos": p["status"].get("qosClass"), "url": f"http://{p['status']['podIP']}:{CPU_PORT}",
           "args": p["spec"]["containers"][0]["args"], "resources": p["spec"]["containers"][0]["resources"]}
          for p in items if p["status"].get("phase") == "Running" and not p["metadata"].get("deletionTimestamp")]
    return sorted(ps, key=lambda p: p["name"])


def pod_cgroup(uid: str) -> str | None:
    """Pod-level cgroup dir (systemd driver): kubepods[-<qos>].slice/...-pod<uid with _>.slice."""
    hits = glob.glob(f"/sys/fs/cgroup/kubepods.slice/**/*pod{uid.replace('-', '_')}.slice", recursive=True)
    return hits[0] if hits else None


def cg_stat(path: str | None) -> dict:
    if not path:
        return {}
    out = {"cpu.max": open(f"{path}/cpu.max").read().strip()}
    for l in open(f"{path}/cpu.stat"):
        k, v = l.split()
        if k in ("usage_usec", "nr_periods", "nr_throttled", "throttled_usec"):
            out[k] = int(v)
    for f in ("cpuset.cpus", "cpuset.cpus.effective"):
        if os.path.exists(f"{path}/{f}"):
            out[f] = open(f"{path}/{f}").read().strip()
    return out


def server_pids(uid: str) -> list[int]:
    """Host PIDs of llama-server inside this pod (the host is the k3s node)."""
    key = uid.replace("-", "_")
    out = []
    for d in glob.glob("/proc/[0-9]*"):
        try:
            if key in open(f"{d}/cgroup").read() and "llama-server" in open(f"{d}/cmdline").read():
                out.append(int(d[6:]))
        except OSError:
            continue
    return out


def expand(cpus: str) -> list[int]:
    out = []
    for part in filter(None, cpus.split(",")):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def siblings(cpus: list[int]) -> dict:
    return {c: open(f"/sys/devices/system/cpu/cpu{c}/topology/thread_siblings_list").read().strip() for c in cpus}


def pod_cpuset(p: dict) -> dict:
    pids = server_pids(p["uid"])
    allowed = None
    if pids:
        for l in open(f"/proc/{pids[0]}/status"):
            if l.startswith("Cpus_allowed_list"):
                allowed = l.split(":")[1].strip()
    cpus = expand(allowed) if allowed else []
    sib = siblings(cpus) if cpus and len(cpus) < 16 else {}
    return {"pod": p["name"], "pids": pids, "Cpus_allowed_list": allowed, "qos": p["qos"],
            "thread_siblings": sib, "full_cores": sorted(set(sib.values())) if sib else None}


def shared_pool_pods() -> list[dict]:
    """Gateway + EPP pods: what the routed probe path runs on (must stay off the exclusive CPUs)."""
    out = []
    for ns, sel in (("inference", "gateway.networking.k8s.io/gateway-name=inference-gateway"),
                    ("inference", "llm-d-router-gateway=llamacpp-pool-epp")):
        items = json.loads(subprocess.run(["kubectl", "-n", ns, "get", "pods", "-l", sel, "-o", "json"], check=True,
                                          capture_output=True, text=True).stdout)["items"]
        out += [{"name": i["metadata"]["name"], "uid": i["metadata"]["uid"]} for i in items]
    return out


def host_snapshot(pods_: list[dict], shared: list[dict]) -> dict:
    stat = open("/proc/stat").readline().split()[1:]
    return {"t": time.time(), "loadavg": open("/proc/loadavg").read().split()[:3],
            "proc_stat_cpu": [int(x) for x in stat],
            "llama": {p["name"]: cg_stat(pod_cgroup(p["uid"])) for p in pods_},
            "shared": {p["name"]: cg_stat(pod_cgroup(p["uid"])).get("usage_usec") for p in shared}}


def snapshot_delta(a: dict, b: dict) -> dict:
    dt_ = b["t"] - a["t"]
    tot = [y - x for x, y in zip(a["proc_stat_cpu"], b["proc_stat_cpu"])]
    idle = tot[3] + tot[4]
    out = {"window_s": round(dt_, 1), "loadavg_start": a["loadavg"], "loadavg_end": b["loadavg"],
           "host_busy_cpus": round((sum(tot) - idle) / sum(tot) * 16, 2) if sum(tot) else None,
           "shared_pod_cpus": {k: round((b["shared"].get(k) or 0) - (a["shared"].get(k) or 0), 0) / 1e6 / dt_
                               for k in b["shared"]}, "llama": {}}
    out["shared_pod_cpus"] = {k: round(v, 3) for k, v in out["shared_pod_cpus"].items()}
    for k, v in b["llama"].items():
        u = a["llama"].get(k, {})
        out["llama"][k] = {"cpu.max": v.get("cpu.max"), "cpus_used": round((v["usage_usec"] - u.get("usage_usec", 0)) / 1e6 / dt_, 2),
                           "nr_throttled_delta": v.get("nr_throttled", 0) - u.get("nr_throttled", 0),
                           "throttled_usec_delta": v.get("throttled_usec", 0) - u.get("throttled_usec", 0),
                           "nr_throttled_total": v.get("nr_throttled"), "throttled_usec_total": v.get("throttled_usec")}
    return out


def provenance(ps: list[dict]) -> dict:
    node = json.loads(sh("kubectl", "get", "nodes", "-o", "json"))["items"][0]
    kc = json.loads(sh("kubectl", "get", "--raw", f"/api/v1/nodes/{node['metadata']['name']}/proxy/configz"))["kubeletconfig"]
    p0 = ps[0]
    props = httpx.get(p0["url"] + "/props", timeout=10).json()
    model = next(a for a in p0["args"] if a.endswith(".gguf"))
    sha = sh("kubectl", "-n", NS, "exec", p0["name"], "-c", "llama-server", "--", "sha256sum", model).split()[0]
    dirty = bool(sh("git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"))
    return {"label": "workstation CPU (WSL2), real llama.cpp, real gateway + EPP",
            "git_sha": sh("git", "-C", str(REPO), "rev-parse", "--short", "HEAD") + ("-dirty" if dirty else ""),
            "k3s": node["status"]["nodeInfo"]["kubeletVersion"],
            "kubelet": {k: kc.get(k) for k in ("cpuManagerPolicy", "cpuManagerPolicyOptions", "reservedSystemCPUs",
                                               "kubeReserved", "systemReserved", "cpuCFSQuota", "featureGates")},
            "node_allocatable_cpu": node["status"]["allocatable"]["cpu"],
            "pods": [pod_cpuset(p) | {"resources": p["resources"], "args": p["args"]} for p in ps],
            "llama_build": props.get("build_info"), "model": model, "model_sha256": sha}


async def lc_gauges(c, url: str) -> dict:
    try:
        r = await c.get(url + "/metrics", timeout=10)
        return {k: float(v) for k, v in LC_RE.findall(r.text)}
    except httpx.HTTPError as e:
        return {"error": type(e).__name__}


async def lc_slots(c, url: str) -> list[dict]:
    try:
        r = await c.get(url + "/slots", timeout=10)
        return [{"id": s["id"], "proc": s["is_processing"], "n_prompt": s.get("n_prompt_tokens"),
                 "n_decoded": (s.get("next_token") or [{}])[0].get("n_decoded") if isinstance(s.get("next_token"), list)
                 else (s.get("next_token") or {}).get("n_decoded")} for s in r.json()]
    except (httpx.HTTPError, ValueError) as e:
        return [{"error": type(e).__name__}]


def cut_prompt(url: str, n_tokens: int) -> str:
    """P8's text ("w0 w1 ...") cut to n_tokens real tokens with the server's own tokenizer (as Build 11)."""
    ids = httpx.post(url + "/tokenize", json={"content": " ".join(f"w{i}" for i in range(n_tokens))}, timeout=30).json()["tokens"]
    return httpx.post(url + "/detokenize", json={"tokens": ids[:n_tokens]}, timeout=30).json()["content"]


def cpu_epp_decisions(log: str) -> dict:
    """x-request-id -> {pick, scores} from the llamacpp-pool EPP's -v=4 JSON log (same lines as epp_decision)."""
    out: dict = {}
    for l in log.splitlines():
        try:
            d = json.loads(l)
        except ValueError:
            continue
        rid = d.get("x-request-id")
        if not rid:
            continue
        e = out.setdefault(rid, {"scores": {}, "pick": None})
        if d.get("msg") == "Calculated score":
            e["scores"].setdefault(d["plugin"].split("/")[0], {})[d["endpoint"]["name"].removesuffix("-rank-0")] = d["score"]
        elif d.get("msg", "").startswith("Completed running picker"):
            e["pick"] = d["result"]["TargetEndpoints"][0]["Endpoint"]["PodName"]
    return out


GW_RE = re.compile(r'^(\S+)\s.*\sroute=inference/llamacpp-pool\sendpoint=([0-9.]+):\d+\s.*\sduration=([0-9.]+)(ms|s|µs|us)\b')


def gateway_picks(since: str, rows: list[dict], ip2pod: dict) -> None:
    """Cross-check of the EPP pick (P9's method, probe_burst.py): the agentgateway access log has endpoint= and
    duration= per request but no request id, so a probe is matched by its start at the gateway (log time - duration)
    within 0.5 s of its send time and duration within 0.5 s of its client e2e. Sets r["gw_log_pick"] (pod name)."""
    lines = []
    for pod in json.loads(kubectl("get", "pods", "-l", "gateway.networking.k8s.io/gateway-name=inference-gateway",
                                  "-o", "json"))["items"]:
        for l in kubectl("logs", pod["metadata"]["name"], f"--since-time={since}").splitlines():
            if m := GW_RE.match(l):
                d = float(m[3]) * {"ms": 1e-3, "s": 1.0, "µs": 1e-6, "us": 1e-6}[m[4]]
                end = dt.datetime.fromisoformat(m[1].replace("Z", "+00:00")).timestamp()
                lines.append((end - d, d, m[2]))
    for r in rows:
        if r.get("t_send") is None:
            continue
        hit = [ip for st, d, ip in lines if abs(st - r["t_send"]) < 0.5 and abs(d - r["e2e_s"]) < 0.5]
        r["gw_log_pick"] = ip2pod.get(hit[0]) if len(hit) == 1 else None
        r["gw_log_matches"] = len(hit)


async def cpu_bg_request(c, url, headers, prompt_, max_tokens, rec):
    """Streamed request that writes t_send / t_first_chunk / t_end into `rec` as they happen, so a request cancelled
    at the end of a block still shows whether it was past its prefill when a probe went out."""
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt_}], "max_tokens": max_tokens,
            "temperature": 0.0, "ignore_eos": True, "stream": True, "stream_options": {"include_usage": True}}
    rec |= {"content_bytes": len(prompt_.encode()), "est_tokens": est_tokens(len(prompt_.encode())), "t_send": time.time()}
    async with c.stream("POST", url + "/v1/chat/completions", json=body, headers=headers, timeout=900) as r:
        rec["status"] = r.status_code
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            rec.setdefault("t_first_chunk", time.time())
            if line != "data: [DONE]" and (u := json.loads(line[6:]).get("usage")):
                rec["prompt_tokens"], rec["completion_tokens"] = u.get("prompt_tokens"), u.get("completion_tokens")
    rec["t_end"] = time.time()


async def cpu_bg_worker(c, url, headers, body, max_tokens, stop, log, meta):
    while not stop.is_set():
        rec = dict(meta)
        log.append(rec)
        try:
            await cpu_bg_request(c, url, headers, f"{uuid.uuid4().hex} {body}", max_tokens, rec)
        except httpx.HTTPError as e:
            rec["error"] = type(e).__name__
            await asyncio.sleep(1.0)


async def cpu_idle_guard(c, ps, timeout) -> dict:
    end = time.monotonic() + timeout
    while True:
        g = await asyncio.gather(*(lc_gauges(c, p["url"]) for p in ps))
        if all(x.get("requests_processing", 1) == 0 and x.get("requests_deferred", 1) == 0 for x in g):
            return {p["name"]: x for p, x in zip(ps, g)}
        if time.monotonic() > end:
            sys.exit(f"idle guard: pods not idle after {timeout}s: {g}")
        await asyncio.sleep(1.0)


async def cpu_block(c, a, blk, L, S, prov, bodies, rng, out_f, bg_f, run_dir):
    ps = [L, S]
    idle = await cpu_idle_guard(c, ps, a.idle_timeout)
    shared = shared_pool_pods()
    snap0 = host_snapshot(ps, shared)
    t_block = dt.datetime.now(dt.timezone.utc)
    stop, bg, tasks = asyncio.Event(), [], []
    want = {"L": a.n_long if a.load_only in ("both", "L") and a.load_path != "none" else 0,
            "S": a.n_short if a.load_only in ("both", "S") and a.load_path != "none" else 0}
    for role, pod, n, tok in (("L", L, want["L"], a.long_tokens), ("S", S, want["S"], a.short_tokens)):
        url, h = (pod["url"], {}) if a.load_path == "direct" else (a.gateway, {"x-pool": "cpu", **pin(pod["name"])})
        for w in range(n):
            meta = {"block": blk, "role": role, "pod": pod["name"], "worker": w, "target_tokens": tok, "load_path": a.load_path}
            tasks.append(asyncio.create_task(cpu_bg_worker(c, url, h, bodies[tok], a.bg_max_tokens, stop, bg, meta)))
    # hold: each pod's processing + deferred == its worker count for --hold-s (placement check, not assumed). S may be
    # one below: a closed-loop short request leaves the count for the moment between its end and the re-send
    # (stock-direct 10:23 run: the exact-count hold never held for 3 s and timed out after 120 s each block).
    t0, held, gate = time.monotonic(), None, {"ok": want == {"L": 0, "S": 0}}
    while want != {"L": 0, "S": 0}:
        g = await asyncio.gather(*(lc_gauges(c, p["url"]) for p in ps))
        inflight = [x.get("requests_processing", 0) + x.get("requests_deferred", 0) for x in g]
        ok = inflight[0] == want["L"] and want["S"] - (1 if want["S"] > 1 else 0) <= inflight[1] <= want["S"]
        now = time.monotonic()
        held = (held or now) if ok else None
        if held and now - held >= a.hold_s:
            gate = {"ok": True, "wait_s": round(now - t0, 1)}
            break
        if now - t0 > a.gate_timeout:
            gate = {"ok": False, "wait_s": round(now - t0, 1), "last": g}
            break
        await asyncio.sleep(0.5)
    rows, last = [], 0.0
    for i in range(a.n_block):
        await asyncio.sleep(rng.uniform(0, a.jitter_s))
        if (w := a.min_gap_s - (time.time() - last)) > 0:
            await asyncio.sleep(w)
        pre = await asyncio.gather(*(lc_gauges(c, p["url"]) for p in ps), lc_slots(c, L["url"]))
        rid = f"p8cpu-{a.label}-{blk}-{i}-{uuid.uuid4().hex[:6]}"
        if a.probe == "gateway":
            url, h = a.gateway, {"x-pool": "cpu", "x-request-id": rid}
        else:
            url, h = (L if a.probe == "L" else S)["url"], {"x-request-id": rid}
        last = time.time()
        rec = await stream_chat(c, url, MODEL, f"{uuid.uuid4().hex} {bodies[a.probe_tokens]}", a.probe_max_tokens, headers=h)
        post = await asyncio.gather(*(lc_slots(c, p["url"]) for p in ps))
        tok, ct = rec.get("prompt_tokens"), rec.get("completion_tokens") or 0
        # cross-check of the pick: which pod holds an idle slot whose last prompt had exactly the probe's token count
        slot_pick = [p["name"] for p, sl in zip(ps, post) if tok and any(not s.get("proc") and tok <= (s.get("n_prompt") or -1) <= tok + ct for s in sl)]
        dec = (ct - 1) / (rec["e2e_s"] - rec["ttft_s"]) if rec.get("ttft_s") is not None and ct > 1 and rec["e2e_s"] > rec["ttft_s"] else None
        rows.append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "label": a.label, "block": blk, "probe_index": i,
                     "probe_id": rid, "probe_target": a.probe, "load_path": a.load_path, "load_only": a.load_only,
                     "L": L["name"], "S": S["name"], "gate": gate,
                     "pre": {"L": pre[0], "S": pre[1], "L_slots": pre[2]}, "post_slots": {"L": post[0], "S": post[1]},
                     "slot_pick": slot_pick, "decode_tok_s": round(dec, 2) if dec else None,
                     **{k: v for k, v in rec.items() if k != "itl_s"},
                     "itl_p50_s": statistics.median(rec["itl_s"]) if rec.get("itl_s") else None})
    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    snap1 = host_snapshot(ps, shared)
    usage = snapshot_delta(snap0, snap1)
    await asyncio.sleep(1.5)                                    # EPP log flush
    log = kubectl("logs", f"deploy/{CPU_EPP}", f"--since-time={t_block.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    (run_dir / f"epp-{a.label}-b{blk}.log").write_text(log)
    decs = cpu_epp_decisions(log)
    if a.probe == "gateway":
        gateway_picks(t_block.strftime('%Y-%m-%dT%H:%M:%SZ'), rows, {p["ip"]: p["name"] for p in ps})
    for r in rows:
        d = decs.get(r["probe_id"], {})
        r["epp_pick_pod"] = d.get("pick")
        r["epp_scores"] = d.get("scores")
        if a.probe in ("L", "S"):
            picked, r["pick_source"] = (L if a.probe == "L" else S)["name"], "forced"
        elif d.get("pick"):
            picked, r["pick_source"] = d["pick"], "epp_log"
        else:                                                   # EPP line missing: fall back to the slot cross-check
            picked = r["slot_pick"][0] if len(r["slot_pick"]) == 1 else None
            r["pick_source"] = "slot_check" if picked else None
        r["pick"] = "L" if picked == L["name"] else "S" if picked == S["name"] else None
        # mid-prefill (Build 11's test): at send, an L background request was sent but had no first chunk yet
        lb = [b for b in bg if b["role"] == "L" and b["t_send"] <= r["t_send"]
              and (b.get("t_first_chunk") or float("inf")) > r["t_send"]]
        r["L_bg_prefilling_at_send"] = len(lb)
        r["usage_window"] = usage
        r["idle_before"] = idle
        r["prov"] = prov
        out_f.write(json.dumps(r) + "\n")
    out_f.flush()
    for b in bg:
        bg_f.write(json.dumps(b) + "\n")
    bg_f.flush()
    return rows


def cpu_summary(rows, label):
    ok = [r for r in rows if r.get("ttft_s") is not None]
    picks = {k: sum(1 for r in ok if r["pick"] == k) for k in ("L", "S")}
    mid = sum(1 for r in ok if r["L_bg_prefilling_at_send"] > 0)
    print(f"\n== {label}: n={len(rows)} ok={len(ok)} picks L/S = {picks['L']}/{picks['S']} mid-L-prefill {mid}/{len(ok)}")
    for k in ("L", "S", None):
        t = sorted(r["ttft_s"] for r in ok if k is None or r["pick"] == k)
        if t:
            d = [r["decode_tok_s"] for r in ok if (k is None or r["pick"] == k) and r["decode_tok_s"]]
            print(f"   {'all' if k is None else 'picked ' + k}: n={len(t)} TTFT p50={statistics.median(t):.3f} "
                  f"p95={t[min(len(t) - 1, math.ceil(0.95 * len(t)) - 1)]:.3f} max={t[-1]:.3f} s; "
                  f"decode p50={statistics.median(d) if d else float('nan'):.1f} tok/s; "
                  f"e2e p50={statistics.median(r['e2e_s'] for r in ok if k is None or r['pick'] == k):.2f} s")


async def main_cpu(a):
    ps = cpu_pods()
    if len(ps) != 2:
        sys.exit(f"need exactly 2 llama.cpp pods, found {[p['name'] for p in ps]}")
    prov = provenance(ps) | {"client": {k: v for k, v in vars(a).items()}, "host": os.uname().nodename}
    run_dir = REPO / "benchmarks/results/probes/p8_cpu"
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = run_dir / f"{stamp}-{a.label}.jsonl"
    print(f"label={a.label} probe={a.probe} load={a.load_path}/{a.load_only} -> {path}")
    print(json.dumps({k: prov[k] for k in ("git_sha", "k3s", "kubelet", "llama_build")}))
    for p in prov["pods"]:
        print(f"  {p['pod']}: qos={p['qos']} Cpus_allowed_list={p['Cpus_allowed_list']} cores={p['full_cores']}")
    rng = random.Random(a.seed)
    bodies = {n: cut_prompt(ps[0]["url"], n) for n in {a.long_tokens, a.short_tokens, a.probe_tokens}}
    rows = []
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=64)) as c:
        with path.open("w") as f, (run_dir / f"{stamp}-{a.label}.bg.jsonl").open("w") as bgf:
            for blk in range(a.blocks):
                L, S = (ps[0], ps[1]) if blk % 2 == 0 else (ps[1], ps[0])
                rows += await cpu_block(c, a, blk, L, S, prov, bodies, rng, f, bgf, run_dir)
                cpu_summary(rows, f"{a.label} after block {blk}")
    print(f"raw: {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--pool", choices=["sim", "cpu"], default="sim", help="cpu: real llama.cpp pool (main_cpu)")
    p.add_argument("--probe", choices=["gateway", "L", "S"], default="gateway", help="cpu: via the EPP, or direct to a pod")
    p.add_argument("--load-only", choices=["both", "L", "S"], default="both", help="cpu: interference runs load one side")
    p.add_argument("--blocks", type=int, default=2, help="cpu: role swaps (block 2 swaps L/S pods)")
    p.add_argument("--n-block", type=int, default=6, help="cpu: probes per block")
    p.add_argument("--bg-max-tokens", type=int, default=64)
    p.add_argument("--probe-max-tokens", type=int, default=32)
    p.add_argument("--hold-s", type=float, default=3.0)
    p.add_argument("--gate-timeout", type=float, default=120)
    p.add_argument("--min-gap-s", type=float, default=2.0)
    p.add_argument("--jitter-s", type=float, default=8.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--label", required=True, help="tag for the output file, e.g. off-pin")
    p.add_argument("--runs", type=int, default=6)
    p.add_argument("--load-path", choices=["direct", "gateway-pin", "none"], default="gateway-pin")
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
    args = p.parse_args()
    asyncio.run(main_cpu(args) if args.pool == "cpu" else main(args))
