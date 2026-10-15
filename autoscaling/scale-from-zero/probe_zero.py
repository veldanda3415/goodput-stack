#!/usr/bin/env python3
"""Scale-from-zero probe for the scratch pool `zero-pool` (GAPS.md P6, #10). SIMULATED backend (sim-zero).

  .venv/bin/python autoscaling/scale-from-zero/probe_zero.py --n 3                      # pool at 0: what do clients get?
  .venv/bin/python autoscaling/scale-from-zero/probe_zero.py --n 3 --scale-up-after 10  # manual 0->1 while requests wait
  .venv/bin/python autoscaling/scale-from-zero/probe_zero.py --n 5 --label keda         # KEDA does the 0->1

Preflight: deployment sim-zero must be at 0 replicas with no pods (waits up to --wait-zero s for that).
Sends --n concurrent streaming requests through the gateway with `x-pool: zero` (spaced by --spacing s);
per request: HTTP status / error, time to response headers, client TTFT, total. Meanwhile every 0.5 s:
the zero-pool EPP's llm_d_epp_flow_control_* and *_ready_* series, sim-zero spec/ready replicas, and pod
events (created, Ready). --scale-up-after S runs `kubectl scale --replicas=1` S s after the first request
(stands in for an autoscaler, to test the hold separately from KEDA).
Output: autoscaling/results/scale-from-zero/<ts>-<label>.jsonl + summary on stdout.
"""
import argparse, asyncio, datetime as dt, json, pathlib, re, subprocess, sys, time, urllib.request
import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from stream_client import stream_chat  # noqa: E402

NS, MODEL, GW, DEP = "inference", "qwen2.5-0.5b-instruct", "http://192.168.117.204", "sim-zero"


def kj(*a):
    r = subprocess.run(["kubectl", "-n", NS, *a, "-o", "json"], capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout) if r.returncode == 0 else None


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--spacing", type=float, default=0.5)
    p.add_argument("--timeout", type=float, default=90)
    p.add_argument("--max-tokens", type=int, default=16)
    p.add_argument("--scale-up-after", type=float)
    p.add_argument("--wait-zero", type=float, default=180)
    p.add_argument("--observe", type=float, default=10, help="s to keep sampling after the last response")
    p.add_argument("--label", default="probe")
    a = p.parse_args()
    out = pathlib.Path("autoscaling/results/scale-from-zero") / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{a.label}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    f = out.open("w")
    t0 = None

    def rec(**kw):
        kw = {"t": now(), "rel_s": round(time.monotonic() - t0, 3) if t0 else None, **kw}
        f.write(json.dumps(kw) + "\n"); f.flush()
        if kw.get("kind") != "sample":
            print(json.dumps(kw), flush=True)

    deadline = time.monotonic() + a.wait_zero
    while True:
        d = kj("get", "deploy", DEP)
        pods = kj("get", "pods", "-l", "app.kubernetes.io/name=vllm-sim-zero")
        if d and d["spec"]["replicas"] == 0 and pods and not pods["items"]:
            break
        if time.monotonic() > deadline:
            sys.exit("preflight: sim-zero not at 0 replicas / pods still present")
        await asyncio.sleep(2)
    epp_ip = kj("get", "pods", "-l", "llm-d-router-gateway=zero-pool-epp")["items"][0]["status"]["podIP"]
    rec(kind="start", n=a.n, scale_up_after=a.scale_up_after, label=a.label)
    t0 = time.monotonic()
    done = asyncio.Event()
    seen_pods = {}
    last_epp = {}

    async def sampler():
        while not done.is_set():
            try:
                txt = await asyncio.to_thread(lambda: urllib.request.urlopen(f"http://{epp_ip}:9090/metrics", timeout=2).read().decode())
                epp = {m.group(1): float(m.group(2)) for m in
                       re.finditer(r'^((?:llm_d_epp_flow_control_\w+|llm_d_epp_ready_endpoints|inference_pool_ready_pods)(?:\{[^}]*\})?)\s+(\S+)', txt, re.M)
                       if "_bucket{" not in m.group(1) and "_sum" not in m.group(1)}
            except Exception as e:
                epp = {"error": str(e)[:100]}
            d = await asyncio.to_thread(kj, "get", "deploy", DEP)
            pods = await asyncio.to_thread(kj, "get", "pods", "-l", "app.kubernetes.io/name=vllm-sim-zero")
            for pd in (pods or {}).get("items", []):
                n = pd["metadata"]["name"]
                rdy = any(c["type"] == "Ready" and c["status"] == "True" for c in pd["status"].get("conditions", []))
                st = seen_pods.setdefault(n, {"ready": False})
                if not st.get("created"):
                    st["created"] = True; rec(kind="event", event="pod_created", pod=n)
                if rdy and not st["ready"]:
                    st["ready"] = True; rec(kind="event", event="pod_ready", pod=n)
            changed = {k: v for k, v in epp.items() if last_epp.get(k) != v}
            if changed:
                rec(kind="epp_change", changed=changed)
                last_epp.update(epp)
            rec(kind="sample", spec=d["spec"].get("replicas") if d else None,
                ready=d["status"].get("readyReplicas", 0) if d else None, epp=epp)
            await asyncio.sleep(0.5)

    async def scaler():
        if a.scale_up_after is None:
            return
        await asyncio.sleep(a.scale_up_after)
        subprocess.run(["kubectl", "-n", NS, "scale", "deploy", DEP, "--replicas=1"], check=True, capture_output=True)
        rec(kind="event", event="manual_scale_to_1")

    async def one(i):
        await asyncio.sleep(i * a.spacing)
        t_send = time.monotonic() - t0
        r = {"kind": "request", "i": i, "send_rel_s": round(t_send, 3)}
        try:
            async with httpx.AsyncClient(headers={"x-pool": "zero"}, timeout=httpx.Timeout(a.timeout, connect=10)) as c:
                res = await stream_chat(c, GW, f"[{i}-{time.time_ns()}] hello", a.max_tokens, model=MODEL, timeout_s=a.timeout)
            r.update(ok=True, status=200, ttft_ms=round(res["ttft_ms"], 1) if res["ttft_ms"] else None,
                     total_ms=round(res["total_ms"], 1), tokens=res["content_chunks"])
        except Exception as e:
            r.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        r["end_rel_s"] = round(time.monotonic() - t0, 3)
        rec(**r)
        return r

    smp = asyncio.create_task(sampler())
    sc = asyncio.create_task(scaler())
    results = await asyncio.gather(*(one(i) for i in range(a.n)))
    await asyncio.sleep(a.observe)
    done.set(); await smp; await sc
    ok = [r for r in results if r["ok"]]
    rec(kind="summary", sent=len(results), ok=len(ok), errors=len(results) - len(ok),
        first_success_end_rel_s=min((r["end_rel_s"] for r in ok), default=None),
        first_ttft_rel_s=min((r["send_rel_s"] + r["ttft_ms"] / 1000 for r in ok if r.get("ttft_ms")), default=None),
        error_kinds=sorted({r["error"][:120] for r in results if not r["ok"]}))
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
