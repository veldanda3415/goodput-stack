#!/usr/bin/env python3
"""P3: does a client disconnect free a llama.cpp slot?  stream vs non-stream.

Per mode: open 2 long requests through the gateway (x-pool: cpu) -> both slots busy;
abort one client after --hold s; sample llama.cpp requests_processing for --watch s.
--direct sends the same requests to the pod (port-forward) to separate engine vs proxy behaviour.
ignore_eos: a generation can't end naturally inside the window and pass for a cancellation.
Slot freed  -> processing drops 2 -> 1 within ~1 s of the abort.
Not freed   -> stays 2 until that generation finishes.
"""
import argparse, asyncio, json, re, subprocess, time
import httpx

NS, MODEL, PF_PORT = "inference", "qwen2.5-0.5b-instruct", 18080
PROC_RE = re.compile(r'^llamacpp:requests_processing\s+([0-9.e+]+)', re.M)


def llama_pod() -> str:
    out = subprocess.run(["kubectl", "-n", NS, "get", "pods", "-l", "llm-d.ai/engine-type=llamacpp",
                          "-o", "json"], check=True, capture_output=True, text=True).stdout
    return json.loads(out)["items"][0]["metadata"]["name"]


async def processing(c: httpx.AsyncClient) -> float:
    r = await c.get(f"http://127.0.0.1:{PF_PORT}/metrics", timeout=5)
    m = PROC_RE.search(r.text)
    return float(m.group(1)) if m else -1


async def long_req(c: httpx.AsyncClient, gw: str, stream: bool, max_tokens: int) -> None:
    body = {"model": MODEL, "stream": stream, "max_tokens": max_tokens, "ignore_eos": True,
            "messages": [{"role": "user", "content": "Write a very long story about a lighthouse."}]}
    async with c.stream("POST", f"{gw}/v1/chat/completions", json=body,
                        headers={"x-pool": "cpu"}, timeout=300) as r:
        async for _ in r.aiter_bytes():
            pass


async def wait_idle(c: httpx.AsyncClient) -> None:
    while await processing(c) > 0:
        await asyncio.sleep(1)


async def run_mode(c, gw: str, stream: bool, a) -> None:
    mode = "stream" if stream else "non-stream"
    await wait_idle(c)
    victim = asyncio.create_task(long_req(c, gw, stream, a.max_tokens))
    keeper = asyncio.create_task(long_req(c, gw, stream, a.max_tokens))
    await asyncio.sleep(a.hold)
    before = await processing(c)
    victim.cancel()                                   # client goes away
    t0 = time.monotonic()
    samples = []
    for _ in range(int(a.watch / 0.5)):
        await asyncio.sleep(0.5)
        samples.append((round(time.monotonic() - t0, 1), await processing(c)))
    keeper.cancel()
    freed = next((t for t, p in samples if p < before), None)
    print(f"\n== {mode}: processing before abort = {before}")
    print("  after abort (s, processing):", samples)
    print(f"  slot freed after ~{freed} s" if freed is not None else "  slot NOT freed during watch window")


async def main(a) -> None:
    pod = llama_pod()
    pf = subprocess.Popen(["kubectl", "-n", NS, "port-forward", f"pod/{pod}", f"{PF_PORT}:8080"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient() as c:
            for _ in range(50):
                try:
                    await processing(c); break
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)
            print("llama.cpp pod:", pod)
            gw = f"http://127.0.0.1:{PF_PORT}" if a.direct else a.gateway
            await run_mode(c, gw, True, a)
            await run_mode(c, gw, False, a)
    finally:
        pf.terminate()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--max-tokens", type=int, default=1500)
    p.add_argument("--hold", type=float, default=3.0, help="s both requests run before abort")
    p.add_argument("--watch", type=float, default=15.0, help="s to sample after abort")
    p.add_argument("--direct", action="store_true", help="bypass gateway (port-forward to pod)")
    asyncio.run(main(p.parse_args()))