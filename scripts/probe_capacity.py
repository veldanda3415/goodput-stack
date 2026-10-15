#!/usr/bin/env python3
"""#21 capacity: closed-loop concurrency ramp, through the gateway (p8-pool, x-pool: p8) vs direct to the pod IPs.

Backend is the llm-d inference sim (SIMULATED) with max-num-seqs 256 (deploy/gateway/p8/sim-p8.yaml), 2 pods.
Per level: C closed-loop workers for --secs each, short unique prompts, max_tokens 8, non-streaming. Records
throughput, client p50/p99, errors, and EPP CPU (kubectl top, the metrics-server window is ~15-60 s so it is a
rough upper-bound sample taken at the end of the level). The load generator is one Python process: where
throughput stops scaling, check whether the client (this script) rather than the gateway is the limit.
"""
import argparse, asyncio, datetime as dt, json, pathlib, subprocess, time, uuid
import httpx

NS = "inference"


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, round(p / 100 * (len(v) - 1)))] if v else float("nan")


async def worker(c, url, hdr, stop, lat, errs):
    while not stop.is_set():
        body = {"model": "qwen2.5-0.5b-instruct", "max_tokens": 8,
                "messages": [{"role": "user", "content": f"cap {uuid.uuid4().hex}"}]}
        t = time.perf_counter()
        try:
            r = await c.post(url, json=body, headers=hdr)
            (lat if r.status_code == 200 else errs).append(time.perf_counter() - t if r.status_code == 200 else r.status_code)
        except Exception as e:
            errs.append(type(e).__name__)


async def level(urls, hdr, conc, secs):
    lim = httpx.Limits(max_connections=conc + 8, max_keepalive_connections=conc + 8)
    async with httpx.AsyncClient(timeout=60, limits=lim) as c:
        stop, lat, errs = asyncio.Event(), [], []
        ws = [asyncio.create_task(worker(c, urls[i % len(urls)], hdr, stop, lat, errs)) for i in range(conc)]
        await asyncio.sleep(secs)
        cpu = sh("kubectl", "-n", NS, "top", "pod", "-l", "llm-d-router-gateway=" + EPP).strip().splitlines()[-1:]
        stop.set()
        await asyncio.gather(*ws)
    return {"conc": conc, "ok": len(lat), "errors": len(errs), "err_kinds": sorted(set(map(str, errs)))[:3],
            "rps": len(lat) / secs, "p50_ms": 1000 * pct(lat, 50), "p99_ms": 1000 * pct(lat, 99), "epp_top": cpu}


async def main(a):
    global EPP
    EPP = a.epp
    ips = json.loads(sh("kubectl", "-n", NS, "get", "pods", "-l", "app.kubernetes.io/name=vllm-sim-p8", "-o", "json"))["items"]
    ips = sorted(p["status"]["podIP"] for p in ips)
    direct = [f"http://{ip}:8000/v1/chat/completions" for ip in ips]
    gw = [f"{a.gateway}/v1/chat/completions"]
    out = []
    for conc in a.levels:
        for path, urls, hdr in (("direct", direct, {}), ("gateway", gw, {"x-pool": "p8"})):
            r = await level(urls, hdr, conc, a.secs)
            r.update(path=path, label=a.label)
            out.append(r)
            print(json.dumps(r), flush=True)
            await asyncio.sleep(2)
    d = pathlib.Path("benchmarks/results/probes/capacity"); d.mkdir(parents=True, exist_ok=True)
    f = d / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{a.label}.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in out))
    print("raw:", f)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--epp", default="p8-pool-epp", help="EPP pod label value (llm-d-router-gateway=)")
    ap.add_argument("--secs", type=float, default=10)
    ap.add_argument("--levels", type=int, nargs="+", default=[1, 4, 16, 64, 128, 256])
    ap.add_argument("--gateway", default="http://192.168.117.204")
    asyncio.run(main(ap.parse_args()))
