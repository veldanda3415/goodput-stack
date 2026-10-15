#!/usr/bin/env python3
"""EPP hop cost: n sequential unique short requests through the gateway to sim-pool (SIMULATED backend).

Records client total-latency p50/p99 and the EPP's own scheduler_e2e_duration histogram delta (mean decision
time) scraped through the API server pod proxy (EPP metrics port 9090). Run once per plugin state, same n:
  make epp-plugin-off && scripts/probe_epp_overhead.py --label off
  make epp-plugin-on  && scripts/probe_epp_overhead.py --label on
"""
import argparse, json, re, statistics, subprocess, time, uuid, datetime as dt, pathlib
import httpx

NS = "inference"


def sh(*a):
    return subprocess.run(a, check=True, capture_output=True, text=True).stdout


def epp_hist(pod):
    t = sh("kubectl", "get", "--raw", f"/api/v1/namespaces/{NS}/pods/{pod}:9090/proxy/metrics")
    out = {}
    for k in ("sum", "count"):
        m = re.search(rf'^inference_extension_scheduler_e2e_duration_seconds_{k}(?:\{{\}})?\s+([0-9.e+-]+)', t, re.M)
        out[k] = float(m.group(1)) if m else 0.0
    return out


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, round(p / 100 * (len(v) - 1)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--gateway", default="http://192.168.117.204")
    a = ap.parse_args()
    pod = sh("kubectl", "-n", NS, "get", "pod", "-l", "llm-d-router-gateway=sim-pool-epp", "-o", "jsonpath={.items[0].metadata.name}").strip()
    h0 = epp_hist(pod)
    lat = []
    with httpx.Client(timeout=30) as c:
        for i in range(a.n):
            body = {"model": "qwen2.5-0.5b-instruct", "max_tokens": 1,
                    "messages": [{"role": "user", "content": f"ping {uuid.uuid4().hex}"}]}
            t = time.perf_counter()
            r = c.post(f"{a.gateway}/v1/chat/completions", json=body)
            lat.append(time.perf_counter() - t)
            assert r.status_code == 200, r.status_code
    h1 = epp_hist(pod)
    dc = (h1["count"] or 0) - (h0["count"] or 0)
    res = {"label": a.label, "ts": dt.datetime.now(dt.timezone.utc).isoformat(), "epp_pod": pod, "n": a.n,
           "client_p50_ms": 1000 * statistics.median(lat), "client_p99_ms": 1000 * pct(lat, 99),
           "client_mean_ms": 1000 * statistics.mean(lat), "client_stdev_ms": 1000 * statistics.stdev(lat),
           "epp_decisions": dc, "epp_sched_mean_ms": 1000 * ((h1["sum"] - h0["sum"]) / dc) if dc else None}
    print(json.dumps(res, indent=1))
    d = pathlib.Path("benchmarks/results/probes/epp_overhead"); d.mkdir(parents=True, exist_ok=True)
    (d / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{a.label}.json").write_text(json.dumps(res, indent=1))


main()
