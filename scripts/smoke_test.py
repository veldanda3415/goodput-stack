"""Smoke test: OpenAI SDK against the inference gateway (non-stream + stream).

Proves the gateway speaks the OpenAI API end to end, and that the final stream chunk carries
`usage` when asked (stream_options.include_usage, #13). --runs N repeats both calls and prints
p50/max of TTFT and total, so one cold connection doesn't stand for the whole picture.

  .venv/bin/python scripts/smoke_test.py                      # sim-pool (default route), 1 run
  .venv/bin/python scripts/smoke_test.py --runs 10 --pool cpu # llamacpp-pool via x-pool: cpu
"""
import argparse, statistics, time
from openai import OpenAI

MODEL = "qwen2.5-0.5b-instruct"

p = argparse.ArgumentParser()
p.add_argument("base", nargs="?", default="http://192.168.117.204/v1")
p.add_argument("--runs", type=int, default=1)
p.add_argument("--pool", help="x-pool header value (cpu -> llamacpp-pool); default route = sim-pool")
a = p.parse_args()
headers = {"x-pool": a.pool} if a.pool else None
client = OpenAI(base_url=a.base, api_key="unused",            # auth will live at the gateway later
                default_headers=headers)

ttfts, totals, missing_usage = [], [], 0
for run in range(a.runs):
    # 1. Non-streaming
    r = client.chat.completions.create(model=MODEL, max_tokens=16,
            messages=[{"role": "user", "content": "Say hi in five words"}])
    if a.runs == 1:
        print("non-stream:", repr(r.choices[0].message.content), r.usage)

    # 2. Streaming, with usage in the final chunk (#13) and client-side TTFT
    t0 = time.perf_counter(); ttft = None; n = 0; usage = None
    stream = client.chat.completions.create(model=MODEL, max_tokens=32, stream=True,
            stream_options={"include_usage": True},
            messages=[{"role": "user", "content": "Count from one to ten"}])
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if chunk.choices and chunk.choices[0].delta.content:
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            n += 1
    total = (time.perf_counter() - t0) * 1000
    ttfts.append(ttft); totals.append(total); missing_usage += usage is None
    print(f"run {run + 1}: content chunks={n}  TTFT={ttft:.1f} ms  total={total:.1f} ms  usage={usage}")

if a.runs > 1:
    print(f"\n{a.runs} runs, pool={a.pool or 'default (sim)'}: "
          f"TTFT p50 {statistics.median(ttfts):.1f} / max {max(ttfts):.1f} ms, "
          f"total p50 {statistics.median(totals):.1f} / max {max(totals):.1f} ms, "
          f"runs without usage: {missing_usage}")
