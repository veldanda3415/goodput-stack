#!/usr/bin/env python3
"""P2: what does the gateway do when the EPP is gone (failureMode: FailOpen)?

Phases: baseline (EPP up) -> EPP scaled to 0 -> EPP restored. Per phase: HTTP codes,
latency p50/max, picks per endpoint from the gateway log. Also reports time-to-recover.
Tests 'EPP gone' (fast connection refused), NOT 'EPP hung' (accepts, never answers).
"""
import argparse, asyncio, collections, datetime as dt, re, statistics, subprocess, time, uuid
import httpx

NS, EPP = "inference", "deploy/sim-pool-epp"
MODEL = "qwen2.5-0.5b-instruct"
PICK_RE = re.compile(r'\sendpoint=([0-9.]+):\d+')


def kubectl(*args: str, check: bool = True) -> str:
    return subprocess.run(["kubectl", "-n", NS, *args], check=check,
                          capture_output=True, text=True).stdout


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def one(client: httpx.AsyncClient, gw: str, tag: str) -> tuple[int, float]:
    body = {"model": MODEL, "max_tokens": 5, "ignore_eos": True,
            "messages": [{"role": "user", "content": f"{tag} {uuid.uuid4().hex}"}]}
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{gw}/v1/chat/completions", json=body, timeout=30)
        code = r.status_code
    except httpx.HTTPError as e:
        code = type(e).__name__
    return code, (time.perf_counter() - t0) * 1000


async def phase(client, gw: str, name: str, n: int) -> None:
    start = now()
    res = [await one(client, gw, name) for _ in range(n)]
    await asyncio.sleep(1)
    log = kubectl("logs", "deploy/inference-gateway", f"--since-time={start}")
    lat = [ms for _, ms in res]
    print(f"\n== {name}")
    print("  codes  :", dict(collections.Counter(c for c, _ in res)))
    print(f"  latency: p50 {statistics.median(lat):.0f} ms, max {max(lat):.0f} ms")
    print("  picks  :", dict(collections.Counter(PICK_RE.findall(log))) or "none logged")
    lines = [l for l in log.splitlines() if "sim-pool" in l]
    if lines:
        print("  sample log:", lines[-1][:400])


async def main(a) -> None:
    async with httpx.AsyncClient() as client:
        await phase(client, a.gateway, "baseline (EPP up)", a.n)

        kubectl("scale", EPP, "--replicas=0")
        kubectl("wait", "--for=delete", "pod", "-l", "llm-d-router-gateway=sim-pool-epp",
                "--timeout=60s", check=False)
        await phase(client, a.gateway, "EPP down", a.n)

        kubectl("scale", EPP, "--replicas=1")
        t0 = time.monotonic()
        kubectl("rollout", "status", EPP, "--timeout=120s")
        ready = time.monotonic() - t0
        await phase(client, a.gateway, "EPP restored", a.n)
        print(f"\nEPP pod Ready after {ready:.1f} s (scale-up to rollout complete)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--n", type=int, default=20)
    asyncio.run(main(p.parse_args()))