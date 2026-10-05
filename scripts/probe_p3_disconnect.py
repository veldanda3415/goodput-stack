#!/usr/bin/env python3
"""P3: does a client disconnect free an engine slot?  stream vs non-stream.

Per mode: open 2 long requests (both slots busy); abort one client after --hold s; sample the
engine's running-requests gauge for --watch s.
Slot freed  -> running drops 2 -> 1 within ~1 s of the abort.
Not freed   -> stays 2 until that generation finishes.

  --backend llamacpp (default)  llamacpp-pool via the gateway (x-pool: cpu); gauge
                                llamacpp:requests_processing through a port-forward to the pod.
  --backend sim                 sim-pool via the gateway (default route); gauge
                                vllm:num_requests_running summed over ALL sim pods, because the EPP
                                may put the two requests on different pods. Pod IPs are scraped
                                directly (works from the k3s host). Results are SIMULATED.
  --direct                      skip the gateway (llama.cpp: port-forward; sim: first pod's IP), to
                                separate engine behaviour from proxy behaviour.
ignore_eos: a generation can't end naturally inside the window and pass for a cancellation.
"""
import argparse, asyncio, json, re, subprocess, time
import httpx

NS, MODEL, PF_PORT = "inference", "qwen2.5-0.5b-instruct", 18080
RUNNING_RE = {"llamacpp": re.compile(r'^llamacpp:requests_processing\s+([0-9.e+]+)', re.M),
              "sim": re.compile(r'^vllm:num_requests_running\{[^}]*\}\s+([0-9.e+]+)', re.M)}
SELECTOR = {"llamacpp": "llm-d.ai/engine-type=llamacpp", "sim": "app.kubernetes.io/name=vllm-sim"}


def pods(backend: str) -> list[tuple[str, str]]:
    out = subprocess.run(["kubectl", "-n", NS, "get", "pods", "-l", SELECTOR[backend], "-o", "json"],
                         check=True, capture_output=True, text=True).stdout
    return sorted((p["metadata"]["name"], p["status"]["podIP"]) for p in json.loads(out)["items"]
                  if p["status"].get("phase") == "Running")


async def running(c: httpx.AsyncClient, a) -> float:
    """Sum of the running gauge over every metrics URL (-1 if a scrape finds no gauge)."""
    total = 0.0
    for url in a.metrics_urls:
        r = await c.get(url, timeout=5)
        m = RUNNING_RE[a.backend].search(r.text)
        if not m:
            return -1
        total += float(m.group(1))
    return total


async def long_req(c: httpx.AsyncClient, a, stream: bool) -> None:
    body = {"model": MODEL, "stream": stream, "max_tokens": a.max_tokens, "ignore_eos": True,
            "messages": [{"role": "user", "content": "Write a very long story about a lighthouse."}]}
    async with c.stream("POST", f"{a.target}/v1/chat/completions", json=body,
                        headers=a.headers, timeout=300) as r:
        async for _ in r.aiter_bytes():
            pass


async def wait_idle(c: httpx.AsyncClient, a) -> None:
    while await running(c, a) > 0:
        await asyncio.sleep(1)


async def run_mode(c, a, stream: bool) -> None:
    mode = "stream" if stream else "non-stream"
    await wait_idle(c, a)
    victim = asyncio.create_task(long_req(c, a, stream))
    keeper = asyncio.create_task(long_req(c, a, stream))
    await asyncio.sleep(a.hold)
    before = await running(c, a)
    victim.cancel()                                   # client goes away
    t0 = time.monotonic()
    samples = []
    for _ in range(int(a.watch / 0.5)):
        await asyncio.sleep(0.5)
        samples.append((round(time.monotonic() - t0, 1), await running(c, a)))
    keeper.cancel()
    freed = next((t for t, p in samples if p < before), None)
    print(f"\n== {mode}: running before abort = {before}")
    print("  after abort (s, running):", samples)
    print(f"  slot freed after ~{freed} s" if freed is not None else "  slot NOT freed during watch window")


async def main(a) -> None:
    found = pods(a.backend)
    pf = None
    if a.backend == "llamacpp":
        pod = found[0][0]
        pf = subprocess.Popen(["kubectl", "-n", NS, "port-forward", f"pod/{pod}", f"{PF_PORT}:8080"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        a.metrics_urls = [f"http://127.0.0.1:{PF_PORT}/metrics"]
        direct, a.headers = f"http://127.0.0.1:{PF_PORT}", {"x-pool": "cpu"}
    else:
        if a.direct:                                  # only the pod we send to
            found = found[:1]
        a.metrics_urls = [f"http://{ip}:8000/metrics" for _, ip in found]
        direct, a.headers = f"http://{found[0][1]}:8000", {}
    a.target = direct if a.direct else a.gateway
    try:
        async with httpx.AsyncClient() as c:
            for _ in range(50):                       # wait for the port-forward / first scrape
                try:
                    await running(c, a); break
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)
            print(f"backend {a.backend} · pods {[n for n, _ in found]} · target {a.target}")
            await run_mode(c, a, True)
            await run_mode(c, a, False)
    finally:
        if pf:
            pf.terminate()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["llamacpp", "sim"], default="llamacpp")
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--max-tokens", type=int, default=1500)
    p.add_argument("--hold", type=float, default=3.0, help="s both requests run before abort")
    p.add_argument("--watch", type=float, default=15.0, help="s to sample after abort")
    p.add_argument("--direct", action="store_true", help="bypass gateway (straight to the pod)")
    asyncio.run(main(p.parse_args()))
