"""Smoke test: OpenAI SDK against the inference gateway (non-stream + stream)."""
import sys, time
from openai import OpenAI

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.117.204/v1"
MODEL = "qwen2.5-0.5b-instruct"
client = OpenAI(base_url=BASE, api_key="unused")   # auth will live at the gateway later

# 1. Non-streaming
r = client.chat.completions.create(model=MODEL, max_tokens=16,
        messages=[{"role": "user", "content": "Say hi in five words"}])
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
print(f"stream: content chunks={n}  TTFT={ttft:.1f} ms  total={total:.1f} ms  usage={usage}")