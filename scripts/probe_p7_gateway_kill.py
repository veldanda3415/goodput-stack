#!/usr/bin/env python3
"""P7: what happens to an in-flight stream when the gateway pod dies? (#20)

Per run: one long streaming completion through the gateway to llamacpp-pool (x-pool: cpu,
ignore_eos). After --kill-after content tokens, `kubectl delete pod` the agentgateway pod (found via
the gateway Deployment's spec.selector.matchLabels, not hardcoded). Records:

  client   tokens received, how the stream ended (exception type, or normal end), kill -> end time
  backend  llamacpp:requests_processing every 0.5 s for --watch s (pod IP, scraped from the k3s host):
           did the slot free up, and when
  recovery new gateway pod Ready (polled ~0.5 s), and the first 200 through the gateway after the kill.
           Recovery pings go to sim-pool (default route, max_tokens 1, new connection each), so they
           never occupy a llama.cpp slot and can't blur the slot signal.

llamacpp-pool on purpose: llama.cpp cancels a stream when a write fails (P3, direct); the sim never cancels.
With more than one gateway replica, only the pod carrying the stream is deleted (--target stream, found from
agentgateway_downstream_connections_total before/after the stream connects); --ping-window keeps the
recovery pings going for a fixed time so a survivor's 200s are visible.
--grace-period is passed to `kubectl delete` (default: the pod's own terminationGracePeriodSeconds, i.e. a
graceful drain; 1 = near-immediate kill).
"""
import argparse, asyncio, datetime as dt, json, pathlib, re, subprocess, time
import httpx

NS, MODEL = "inference", "qwen2.5-0.5b-instruct"
LLAMA_SELECTOR = "llm-d.ai/engine-type=llamacpp"
PROC_RE = re.compile(r'^llamacpp:requests_processing\s+([0-9.e+]+)', re.M)
CONN_RE = re.compile(r'^agentgateway_downstream_connections_total\{[^}]*\}\s+([0-9.e+]+)', re.M)


def kubectl(*args: str, check: bool = True) -> str:
    return subprocess.run(["kubectl", "-n", NS, *args], check=check,
                          capture_output=True, text=True).stdout


def gw_selector(deploy: str) -> str:
    labels = json.loads(kubectl("get", "deploy", deploy, "-o", "jsonpath={.spec.selector.matchLabels}"))
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


def gw_pods(selector: str) -> dict[str, bool]:
    """name -> Ready, for pods that are not terminating."""
    items = json.loads(kubectl("get", "pods", "-l", selector, "-o", "json"))["items"]
    return {p["metadata"]["name"]: any(c["type"] == "Ready" and c["status"] == "True"
                                       for c in p["status"].get("conditions", []))
            for p in items if not p["metadata"].get("deletionTimestamp")}


def gw_conns(selector: str) -> dict[str, float]:
    """name -> agentgateway_downstream_connections_total (0 before a pod's first connection), Running pods."""
    items = json.loads(kubectl("get", "pods", "-l", selector, "-o", "json"))["items"]
    out = {}
    for p in items:
        ip = p["status"].get("podIP")
        if p["metadata"].get("deletionTimestamp") or not ip:
            continue
        try:
            txt = httpx.get(f"http://{ip}:15020/metrics", timeout=2).text
            out[p["metadata"]["name"]] = sum(float(m.group(1)) for m in CONN_RE.finditer(txt))
        except Exception:
            out[p["metadata"]["name"]] = float("nan")
    return out


def llama_ip() -> str:
    items = json.loads(kubectl("get", "pods", "-l", LLAMA_SELECTOR, "-o", "json"))["items"]
    return next(p["status"]["podIP"] for p in items if p["status"].get("phase") == "Running")


async def processing(c: httpx.AsyncClient, url: str) -> float:
    r = await c.get(url, timeout=2)
    return float(PROC_RE.search(r.text).group(1))


async def stream(a, st: dict, kill_evt: asyncio.Event) -> None:
    body = {"model": MODEL, "stream": True, "max_tokens": a.max_tokens, "ignore_eos": True,
            "messages": [{"role": "user", "content": "Write a very long story about a lighthouse."}]}
    st.update(tokens=0, done=False, finish_reason=None, error=None)
    timeout = httpx.Timeout(10, read=a.read_timeout)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", f"{a.gateway}/v1/chat/completions", json=body,
                                headers={"x-pool": "cpu"}) as r:
                st["status"] = r.status_code
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    if line == "data: [DONE]":
                        st["done"] = True
                        continue
                    ch = json.loads(line[6:])
                    for choice in ch.get("choices", []):
                        if choice.get("delta", {}).get("content"):
                            st["tokens"] += 1
                            if st["tokens"] == a.kill_after:
                                st["tokens_at_kill"] = st["tokens"]
                                kill_evt.set()
                        st["finish_reason"] = choice.get("finish_reason") or st["finish_reason"]
    except Exception as e:                            # the result, not a crash
        st["error"] = f"{type(e).__module__}.{type(e).__name__}: {e}"[:300]
    st["end"] = time.monotonic()
    kill_evt.set()                                    # never leave the killer waiting


async def kill(a, selector: str, st: dict, kill_evt: asyncio.Event) -> None:
    await kill_evt.wait()
    if "tokens_at_kill" not in st:                    # stream ended before K tokens: no kill
        return
    # With >1 gateway replica, kill only the pod that accepted the stream's connection: the one whose
    # downstream connection counter went up since the snapshot taken just before the stream started.
    # --target all keeps the original behaviour (delete every gateway pod).
    pods = list(gw_pods(selector))
    if a.target == "stream" and len(pods) > 1:
        now = gw_conns(selector)
        grew = [n for n in pods if now.get(n, 0) > st["conns0"].get(n, 0)]
        st["stream_pod_candidates"] = grew
        if len(grew) != 1:
            st["error_kill"] = f"cannot tell the stream's pod: connection counters grew on {grew}"
            return
        pods = grew
        st["survivors"] = [n for n in gw_pods(selector) if n not in pods]
    st["old_pods"] = pods
    st["t_kill"] = time.monotonic()
    st["kill_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    args = ["delete", "pod", *st["old_pods"], "--wait=false"]
    if a.grace_period is not None:
        args.append(f"--grace-period={a.grace_period}")
    await asyncio.to_thread(kubectl, *args)


async def watch_slot(a, url: str, st: dict) -> None:
    samples = []
    async with httpx.AsyncClient() as c:
        while "t_kill" not in st or time.monotonic() - st["t_kill"] < a.watch:
            if "end" in st and "t_kill" not in st:
                break
            try:
                samples.append((time.monotonic(), await processing(c, url)))
            except Exception as e:
                samples.append((time.monotonic(), type(e).__name__))
            await asyncio.sleep(0.5)
    st["slot_samples"] = samples


async def watch_recovery(a, selector: str, st: dict) -> None:
    while "t_kill" not in st:
        if "end" in st:
            return
        await asyncio.sleep(0.05)
    t0, old = st["t_kill"], set(st["old_pods"]) | set(st.get("survivors", []))   # "new" = the replacement only
    pings, ready_at = [], None
    body = {"model": MODEL, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}
    while time.monotonic() - t0 < a.recover_window:
        if ready_at is None:
            pods = await asyncio.to_thread(gw_pods, selector)
            new = [n for n, ok in pods.items() if n not in old and ok]
            if new:
                ready_at = round(time.monotonic() - t0, 2)
                st["new_pod"] = new[0]
        t = time.monotonic() - t0
        try:
            async with httpx.AsyncClient(timeout=3) as c:  # fresh connection every ping
                r = await c.post(f"{a.gateway}/v1/chat/completions", json=body)
                res = r.status_code
        except Exception as e:
            res = type(e).__name__
        pings.append((round(t, 2), res))
        if ready_at is not None and res == 200 and t >= ready_at and t >= a.ping_window:
            break
        await asyncio.sleep(0.5)
    st["new_ready_s"], st["pings"] = ready_at, pings


async def wait_settled(a, selector: str, url: str) -> None:
    """Start from: as many Ready gateway pods as the Deployment wants, none terminating, llama.cpp idle."""
    want = int(kubectl("get", "deploy", a.gateway_deploy, "-o", "jsonpath={.spec.replicas}"))
    async with httpx.AsyncClient() as c:
        for _ in range(240):
            items = json.loads(kubectl("get", "pods", "-l", selector, "-o", "json"))["items"]
            pods = gw_pods(selector)
            if len(items) == want and all(pods.values()) and await processing(c, url) == 0:
                return
            await asyncio.sleep(0.5)
    raise SystemExit("not settled after 120 s (gateway pods or llama.cpp busy)")


def summarise(st: dict) -> dict:
    t0 = st.get("t_kill")
    rel = lambda t: round(t - t0, 2)
    out = {k: st.get(k) for k in ("kill_utc", "status", "tokens_at_kill", "tokens", "done",
                                  "finish_reason", "error", "old_pods", "new_pod", "new_ready_s",
                                  "survivors", "stream_pod_candidates", "error_kill")}
    if t0 is None:
        out["note"] = "stream ended before --kill-after tokens; no kill"
        return out
    out["client_end_s"] = rel(st["end"])
    out["tokens_after_kill"] = st["tokens"] - st["tokens_at_kill"]
    samples = [(rel(t), v) for t, v in st["slot_samples"] if t >= t0]
    # Runs start from processing 0 (wait_settled), so the first sample after the kill is our stream's
    # slot and "freed" = the first later sample back at 0. (The last pre-kill sample can predate the
    # request reaching the engine, so it is not used.)
    out["processing_at_kill"] = samples[0][1] if samples else None
    out["slot_freed_s"] = next((t for t, v in samples[1:] if v == 0), None)
    out["slot_samples"] = samples
    pings = st.get("pings", [])
    out["pings_failed"] = sum(1 for _, r in pings if r != 200)
    out["first_200_s"] = next((t for t, r in pings if r == 200), None)
    out["first_200_after_ready_s"] = next((t for t, r in pings if r == 200 and st.get("new_ready_s")
                                           is not None and t >= st["new_ready_s"]), None)
    out["pings"] = pings
    return out


async def main(a) -> None:
    selector, url = gw_selector(a.gateway_deploy), f"http://{llama_ip()}:8080/metrics"
    out_dir = pathlib.Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl"
    print(f"gateway pods: -l {selector} (from deploy/{a.gateway_deploy} spec.selector.matchLabels)")
    print(f"slot gauge  : {url}   grace-period: {a.grace_period if a.grace_period is not None else 'pod default'}")
    for i in range(1, a.runs + 1):
        await wait_settled(a, selector, url)
        st, ev = {"conns0": gw_conns(selector)}, asyncio.Event()
        await asyncio.gather(stream(a, st, ev), kill(a, selector, st, ev),
                             watch_slot(a, url, st), watch_recovery(a, selector, st))
        s = {"run": i, "grace_period": a.grace_period, "max_tokens": a.max_tokens, **summarise(st)}
        with out_file.open("a") as f:
            f.write(json.dumps(s) + "\n")
        print(f"\n== run {i}  kill at {s.get('kill_utc')}  HTTP {s.get('status')}")
        print(f"  client : tokens {s.get('tokens_at_kill')} at kill, {s.get('tokens')} total "
              f"(+{s.get('tokens_after_kill')} after kill); [DONE] {s.get('done')}, finish {s.get('finish_reason')}")
        print(f"           ended {s.get('client_end_s')} s after kill; error: {s.get('error')}")
        print(f"  backend: requests_processing at kill {s.get('processing_at_kill')}; "
              f"slot freed {s.get('slot_freed_s')} s after kill" if s.get('slot_freed_s') is not None
              else f"  backend: requests_processing at kill {s.get('processing_at_kill')}; "
                   f"slot NOT freed within {a.watch:.0f} s")
        print(f"  gateway: new pod {s.get('new_pod')} Ready {s.get('new_ready_s')} s after kill; "
              f"first 200 {s.get('first_200_s')} s, first 200 after Ready {s.get('first_200_after_ready_s')} s, "
              f"failed pings {s.get('pings_failed')}")
        print(f"  killed : {s.get('old_pods')}  survivors: {s.get('survivors')}  {s.get('error_kill') or ''}")
    print(f"\nraw: {out_file}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--gateway-deploy", default="inference-gateway", help="agentgateway Deployment")
    p.add_argument("--kill-after", type=int, default=20, help="content tokens before the pod delete (K)")
    p.add_argument("--max-tokens", type=int, default=1900, help="per-slot ctx is 2048 (-c 4096 / --parallel 2)")
    p.add_argument("--grace-period", type=int, help="kubectl delete --grace-period (default: pod's own)")
    p.add_argument("--watch", type=float, default=60.0, help="s to sample requests_processing after the kill")
    p.add_argument("--recover-window", type=float, default=120.0, help="s to wait for Ready + first 200")
    p.add_argument("--read-timeout", type=float, default=30.0, help="client read timeout on the stream")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--target", choices=["stream", "all"], default="stream",
                   help="with >1 gateway pod: delete only the stream's pod (default) or every pod")
    p.add_argument("--ping-window", type=float, default=0.0,
                   help="keep pinging at least this many s after the kill (default: stop at first 200 after Ready)")
    p.add_argument("--out-dir", default="benchmarks/results/probes/p7")
    asyncio.run(main(p.parse_args()))
