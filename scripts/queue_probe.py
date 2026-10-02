#!/usr/bin/env python3
"""scripts/queue_probe.py — Week 1 D4 queueing probe (stdlib only).

Fires N concurrent streaming requests at a llama.cpp server (or vLLM / the vLLM simulator)
and prints, per request: client TTFT (what the user waits) vs engine prompt_ms (llama.cpp only).
While they run, samples /metrics for running / queued requests (llamacpp:requests_processing /
requests_deferred, or vllm:num_requests_running / num_requests_waiting).

Usage:
  python3 scripts/queue_probe.py --url http://127.0.0.1:8080 --n 6 --max-tokens 80
  make sim-probe ARGS="--n 6"     # simulator Service (model name is required by vLLM APIs)
"""
import argparse
import json
import threading
import time
import urllib.request

PROMPT = "Request {i}: list three facts about the number {i}. Nonce {nonce}."


def stream_one(url, i, max_tokens, t0, out, model=None):
    body = {
        "messages": [{"role": "user", "content": PROMPT.format(i=i, nonce=time.time_ns())}],
        "stream": True,
        "max_tokens": max_tokens,
        "cache_prompt": False,   # defeat prefix cache (open issue #1)
    }
    if model:
        body["model"] = model
    req = urllib.request.Request(
        f"{url}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    sent = time.perf_counter()
    first = None
    n_tok = 0
    timings = {}
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            delta = (chunk.get("choices") or [{}])[0].get("delta", {})
            if delta.get("content"):
                n_tok += 1
                if first is None:
                    first = time.perf_counter()
            if "timings" in chunk:
                timings = chunk["timings"]
    done = time.perf_counter()
    out[i] = {
        "start_s": sent - t0,
        "ttft_ms": (first - sent) * 1000 if first else None,
        "e2e_ms": (done - sent) * 1000,
        "tokens": n_tok,
        "engine_prompt_ms": timings.get("prompt_ms"),
        "engine_predicted_per_token_ms": timings.get("predicted_per_token_ms"),
    }


def sample_metrics(url, stop, samples, t0):
    while not stop.is_set():
        try:
            txt = urllib.request.urlopen(f"{url}/metrics", timeout=2).read().decode()
            vals = {}
            names = {"llamacpp:requests_processing": "requests_processing",
                     "llamacpp:requests_deferred": "requests_deferred",
                     "vllm:num_requests_running": "requests_processing",   # same meaning
                     "vllm:num_requests_waiting": "requests_deferred"}
            for ln in txt.splitlines():
                key = names.get(ln.split("{", 1)[0].split(" ", 1)[0])
                if key:
                    vals[key] = vals.get(key, 0.0) + float(ln.split()[-1])
            samples.append((time.perf_counter() - t0, vals))
        except Exception as e:  # metrics off or server busy
            samples.append((time.perf_counter() - t0, {"error": str(e)}))
        stop.wait(0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=80)
    ap.add_argument("--model", help="model name to send (needed for vLLM / the simulator)")
    a = ap.parse_args()

    t0 = time.perf_counter()
    results, samples, stop = {}, [], threading.Event()
    mt = threading.Thread(target=sample_metrics, args=(a.url, stop, samples, t0), daemon=True)
    mt.start()
    threads = [threading.Thread(target=stream_one, args=(a.url, i, a.max_tokens, t0, results, a.model))
               for i in range(a.n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    mt.join()

    print(f"\n{'req':>3} {'client TTFT ms':>15} {'engine prompt_ms':>17} {'gap ms':>9} {'e2e ms':>9} {'tok':>4} {'ms/tok':>7}")
    for i in sorted(results, key=lambda k: results[k]["ttft_ms"] or 1e12):
        r = results[i]
        gap = (r["ttft_ms"] - r["engine_prompt_ms"]) if r["ttft_ms"] and r["engine_prompt_ms"] else None
        fmt = lambda v, p=1: f"{v:.{p}f}" if isinstance(v, (int, float)) else "-"
        print(f"{i:>3} {fmt(r['ttft_ms']):>15} {fmt(r['engine_prompt_ms']):>17} {fmt(gap):>9} "
              f"{fmt(r['e2e_ms']):>9} {r['tokens']:>4} {fmt(r['engine_predicted_per_token_ms']):>7}")
    peak_def = max((s[1].get("requests_deferred", 0) for s in samples), default=0)
    peak_proc = max((s[1].get("requests_processing", 0) for s in samples), default=0)
    print(f"\npeak requests_processing={peak_proc:.0f}  peak requests_deferred={peak_def:.0f}  ({len(samples)} metric samples)")
    print("gap = client TTFT - engine prompt_ms ~= time spent queued before a slot (plus network/port-forward).")


if __name__ == "__main__":
    main()