#!/usr/bin/env python3
"""P1: does the EPP steer new requests away from a sim pod whose queue is backed up?

Saturates pod A directly (port-forward, bypassing the gateway and EPP), so the EPP can
only learn A is busy by scraping A's /metrics. Then sends short requests through the
gateway with unique prompts (neutralises the prefix-cache scorer) and counts picks per
endpoint from the gateway log.

  --no-saturate   control run: same gateway requests, A idle (expect a rough split).
                  Refuses to run ("control invalid") unless A shows running=0 and waiting=0:
                  a pod still draining an earlier saturation run would bias the control.
"""
import argparse, asyncio, collections, datetime as dt, json, re, subprocess, sys, time, uuid
import httpx

NS = "inference"
SIM_SELECTOR = "app.kubernetes.io/name=vllm-sim"
MODEL = "qwen2.5-0.5b-instruct"
PF_PORT = 18000
GAUGE_RE = re.compile(r'^vllm:num_requests_(running|waiting)\{[^}]*\}\s+([0-9.e+]+)', re.M)
PICK_RE = re.compile(r'selected_endpoint=([0-9.]+):\d+')


def kubectl(*args: str) -> str:
    return subprocess.run(["kubectl", "-n", NS, *args], check=True,
                          capture_output=True, text=True).stdout


def sim_pods() -> list[tuple[str, str]]:
    items = json.loads(kubectl("get", "pods", "-l", SIM_SELECTOR, "-o", "json"))["items"]
    pods = [(p["metadata"]["name"], p["status"]["podIP"]) for p in items
            if p["status"].get("phase") == "Running"]
    return sorted(pods, key=lambda p: p[1])


async def gauges(client: httpx.AsyncClient) -> dict[str, float]:
    r = await client.get(f"http://127.0.0.1:{PF_PORT}/metrics", timeout=5)
    return {k: float(v) for k, v in GAUGE_RE.findall(r.text)}


async def long_request(client: httpx.AsyncClient, max_tokens: int) -> None:
    body = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": max_tokens, "ignore_eos": True}
    try:
        await client.post(f"http://127.0.0.1:{PF_PORT}/v1/chat/completions", json=body, timeout=300)
    except (httpx.HTTPError, asyncio.CancelledError):
        pass


async def gateway_request(client: httpx.AsyncClient, gw: str, i: int) -> int:
    body = {"model": MODEL, "max_tokens": 5,
            "messages": [{"role": "user", "content": f"probe {i} {uuid.uuid4().hex}"}]}
    r = await client.post(f"{gw}/v1/chat/completions", json=body, timeout=60)
    return r.status_code


async def main(a: argparse.Namespace) -> None:
    pods = sim_pods()
    if len(pods) < 2:
        sys.exit(f"need >=2 running sim pods, found {pods}")
    (a_name, a_ip), (b_name, b_ip) = pods[0], pods[1]
    print(f"A = {a_name} {a_ip}   B = {b_name} {b_ip}")

    pf = subprocess.Popen(["kubectl", "-n", NS, "port-forward", f"pod/{a_name}", f"{PF_PORT}:8000"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(50):                      # wait for the tunnel
                try:
                    await gauges(client); break
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)
            idle = await gauges(client)
            print("A idle      :", idle)
            if a.no_saturate and (idle.get("running", 0) or idle.get("waiting", 0)):
                sys.exit(f"control invalid: A not idle {idle}; wait for it to drain and rerun")

            load = []
            if not a.no_saturate:
                load = [asyncio.create_task(long_request(client, a.max_tokens)) for _ in range(a.long)]
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    g = await gauges(client)
                    if g.get("waiting", 0) > 0:
                        break
                    await asyncio.sleep(0.2)
                print("A saturated :", g)
                await asyncio.sleep(a.settle)        # let EPP scrape the new state

            start = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            codes = [await gateway_request(client, a.gateway, i) for i in range(a.n)]
            print("A after     :", await gauges(client))
            print("HTTP codes  :", dict(collections.Counter(codes)))

            for t in load:
                t.cancel()
    finally:
        pf.terminate()

    await asyncio.sleep(1)                           # let the gateway flush its log
    picks = collections.Counter(PICK_RE.findall(
        kubectl("logs", "deploy/inference-gateway", f"--since-time={start}")))
    label = {a_ip: "A (saturated)" if not a.no_saturate else "A", b_ip: "B"}
    print("Picks       :", {f"{label.get(ip, ip)} {ip}": n for ip, n in picks.items()})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gateway", default="http://192.168.117.204")
    p.add_argument("--n", type=int, default=20, help="gateway requests")
    p.add_argument("--long", type=int, default=8, help="long requests sent directly to A")
    p.add_argument("--max-tokens", type=int, default=1000)
    p.add_argument("--settle", type=float, default=1.0, help="s to wait after A saturates")
    p.add_argument("--no-saturate", action="store_true", help="control run")
    asyncio.run(main(p.parse_args()))

