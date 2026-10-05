#!/usr/bin/env python3
"""scripts/watch_metrics.py — live view of a backend's /metrics while a benchmark runs (stdlib only).

One line per interval: requests running / waiting, generated tok/s over the interval, and
(vLLM / simulator) the server's own mean TTFT, queue time and ITL for requests that finished
in that interval. Works for llama.cpp (llamacpp:*) and vLLM / llm-d-inference-sim (vllm:*).

Usage:
  make sim-watch                                           # simulator Service, from the k3s host
  python3 scripts/watch_metrics.py --url http://<clusterIP>:8000 --interval 1
  python3 scripts/watch_metrics.py --url http://127.0.0.1:18080        # llama.cpp via port-forward
Ctrl-C stops it.
"""
import argparse
import time
import urllib.request

# (column, llama.cpp name, vLLM name) - prefixes stripped, label sets summed
GAUGES = [("running", "requests_processing", "num_requests_running"),
          ("waiting", "requests_deferred", "num_requests_waiting")]
TOKENS = ("tokens_predicted_total", "generation_tokens_total")
HISTOGRAMS = [("srv TTFT ms", "time_to_first_token_seconds"),
              ("srv queue ms", "request_queue_time_seconds"),
              ("srv ITL ms", "inter_token_latency_seconds")]


def scrape(url):
    out = {}
    for line in urllib.request.urlopen(f"{url}/metrics", timeout=3).read().decode().splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        name = name.split("{", 1)[0]
        if name.endswith("_bucket"):
            continue
        key = name.removeprefix("llamacpp:").removeprefix("vllm:")
        try:
            out[key] = out.get(key, 0.0) + float(value)
        except ValueError:
            pass
    return out


def first(m, names):
    return next((m[n] for n in names if n in m), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()

    prev, t_prev = scrape(a.url), time.monotonic()
    vllm = "num_requests_running" in prev
    cols = ["time", "running", "waiting", "tok/s"] + ([h for h, _ in HISTOGRAMS] if vllm else [])
    print(" ".join(f"{c:>12}" for c in cols), flush=True)
    try:
        while True:
            time.sleep(a.interval)
            try:
                cur, now = scrape(a.url), time.monotonic()
            except OSError as exc:
                print(f"{time.strftime('%H:%M:%S'):>12} scrape failed: {exc}", flush=True)
                continue
            row = [time.strftime("%H:%M:%S")]
            row += [f"{first(cur, names) or 0:.0f}" for _, *names in GAUGES]
            dt = now - t_prev
            tok = (first(cur, TOKENS) or 0) - (first(prev, TOKENS) or 0)
            row.append(f"{tok / dt:.1f}" if dt > 0 else "-")
            if vllm:
                for _, h in HISTOGRAMS:
                    n = cur.get(f"{h}_count", 0) - prev.get(f"{h}_count", 0)
                    s = cur.get(f"{h}_sum", 0) - prev.get(f"{h}_sum", 0)
                    row.append(f"{s / n * 1000:.1f}" if n > 0 else "-")
            print(" ".join(f"{v:>12}" for v in row), flush=True)
            prev, t_prev = cur, now
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
