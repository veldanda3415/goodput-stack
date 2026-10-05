#!/usr/bin/env python3
"""scripts/stream_client.py — measure real TTFT and ITL from an OpenAI-compatible stream.

curl shows *a* first byte, but the first SSE chunk of a chat stream is usually role-only
(`delta: {"role": "assistant"}`, no text). This client tells them apart:

    TTFB  = request sent -> first SSE chunk of any kind (often role-only)
    TTFT  = request sent -> first chunk whose delta.content is non-empty   <- what users feel
    ITL   = gaps between consecutive content chunks after the first
    total = request sent -> stream finished ([DONE])

llama.cpp also puts its own `timings` (prompt_n, prompt_ms, cache_n, ...) on the final
chunk, so TTFT can be compared with the engine's prefill time: TTFT - prompt_ms is
HTTP + queueing + first decode step.

Usage (engine via port-forward):
  kubectl -n inference port-forward svc/inf-llamacpp 18080:8080 &
  .venv/bin/python scripts/stream_client.py --url http://127.0.0.1:18080
  .venv/bin/python scripts/stream_client.py --runs 5 --max-tokens 64
  .venv/bin/python scripts/stream_client.py --parallel 4 --runs 3     # 4 concurrent streams x 3 requests
  .venv/bin/python scripts/stream_client.py --prompt-file long.txt --json

Reuse: `stream_chat()` is importable (async) and returns one dict per request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time

import httpx

DEFAULT_PROMPT = "Explain in a few sentences why the sky is blue."


def pct(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in 0..100)."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


async def stream_chat(client: httpx.AsyncClient, url: str, prompt: str, max_tokens: int,
                      model: str | None = None, cache_prompt: bool = False,
                      timeout_s: float = 300.0) -> dict:
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},  # final chunk carries token usage
        "cache_prompt": cache_prompt,               # llama.cpp extension: False = cold prefill every run
    }
    if model:
        body["model"] = model

    t_sent = time.perf_counter()
    t_first_chunk = None
    content_times: list[float] = []
    n_role_only = 0
    text: list[str] = []
    usage, timings, finish_reason = {}, {}, None

    async with client.stream("POST", f"{url}/v1/chat/completions", json=body, timeout=timeout_s) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {(await resp.aread()).decode(errors='replace')[:300]}")
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue  # blank keep-alive lines, comments
            now = time.perf_counter()
            data = line[5:].strip()
            if data == "[DONE]":
                break
            t_first_chunk = t_first_chunk or now
            chunk = json.loads(data)
            usage = chunk.get("usage") or usage
            timings = chunk.get("timings") or timings
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                finish_reason = choice.get("finish_reason") or finish_reason
                if delta.get("content"):            # non-null, non-empty text
                    content_times.append(now)
                    text.append(delta["content"])
                elif "role" in delta:
                    n_role_only += 1                # the chunk curl would call "first byte"
    t_end = time.perf_counter()

    itl = [(b - a) * 1000 for a, b in zip(content_times, content_times[1:])]
    ttft = (content_times[0] - t_sent) * 1000 if content_times else None
    return {
        "ttfb_ms": (t_first_chunk - t_sent) * 1000 if t_first_chunk else None,
        "ttft_ms": ttft,
        "itl_ms": itl,
        "itl_mean_ms": statistics.fmean(itl) if itl else None,
        "itl_p50_ms": pct(itl, 50),
        "itl_p95_ms": pct(itl, 95),
        "content_chunks": len(content_times),
        "role_only_chunks": n_role_only,
        "completion_tokens": usage.get("completion_tokens"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "total_ms": (t_end - t_sent) * 1000,
        "finish_reason": finish_reason,
        "server_prompt_n": timings.get("prompt_n"),
        "server_cache_n": timings.get("cache_n"),
        "server_prompt_ms": timings.get("prompt_ms"),
        "server_predicted_per_token_ms": timings.get("predicted_per_token_ms"),
        "ttft_minus_prompt_ms": ttft - timings["prompt_ms"] if ttft is not None and "prompt_ms" in timings else None,
        "text": "".join(text),
    }


def fmt(v, unit: str = "ms") -> str:
    return "-" if v is None else f"{v:,.1f} {unit}".rstrip()


def print_run(i: int, r: dict) -> None:
    print(f"run {i}")
    print(f"  TTFB (first chunk, role-only={r['role_only_chunks'] > 0}) {fmt(r['ttfb_ms'])}")
    print(f"  TTFT (first content chunk)          {fmt(r['ttft_ms'])}")
    print(f"  server prompt_ms                    {fmt(r['server_prompt_ms'])}"
          f"   (prompt_n={r['server_prompt_n']}, cache_n={r['server_cache_n']})")
    print(f"  TTFT - prompt_ms                    {fmt(r['ttft_minus_prompt_ms'])}")
    print(f"  ITL mean / p50 / p95                {fmt(r['itl_mean_ms'])} / {fmt(r['itl_p50_ms'])} / {fmt(r['itl_p95_ms'])}"
          f"   (server {fmt(r['server_predicted_per_token_ms'])}/token)")
    print(f"  tokens                              {r['content_chunks']} content chunks"
          f" / {r['completion_tokens']} completion_tokens (usage), finish={r['finish_reason']}")
    print(f"  total                               {fmt(r['total_ms'])}")


async def poll_metrics(client: httpx.AsyncClient, url: str, stop: asyncio.Event, out: dict) -> None:
    """Track peak requests_processing / requests_deferred from llama.cpp /metrics (if enabled)."""
    while not stop.is_set():
        try:
            text = (await client.get(f"{url}/metrics", timeout=2.0)).text
            for line in text.splitlines():
                for key in ("requests_processing", "requests_deferred"):
                    if line.startswith(f"llamacpp:{key} "):
                        out[key] = max(out.get(key, 0), float(line.split()[-1]))
            out["available"] = True
        except (httpx.HTTPError, ValueError):
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass


async def run_parallel(args, prompt: str) -> tuple[list[dict], float, dict]:
    """`parallel` streams, each sending `runs` requests back to back (closed loop)."""
    results: list[dict] = []
    peaks: dict = {}
    rng = random.Random(0)
    delays = [0.0] + [rng.uniform(0, args.stagger) for _ in range(args.parallel - 1)]
    limits = httpx.Limits(max_connections=args.parallel + 2, max_keepalive_connections=args.parallel + 2)
    async with httpx.AsyncClient(limits=limits) as client:
        t0 = time.perf_counter()

        async def stream_worker(w: int) -> None:
            await asyncio.sleep(delays[w])
            for k in range(args.runs):
                start = time.perf_counter() - t0
                try:
                    r = await stream_chat(client, args.url, prompt, args.max_tokens, args.model, args.cache_prompt)
                except (httpx.HTTPError, RuntimeError, json.JSONDecodeError) as exc:
                    r = {"error": f"{type(exc).__name__}: {exc}"}
                r |= {"stream": w + 1, "seq": k + 1, "start_s": start}
                results.append(r)
                if args.json:
                    print(json.dumps({k: v for k, v in r.items() if k not in ("itl_ms", "text")}), flush=True)

        stop = asyncio.Event()
        poller = asyncio.create_task(poll_metrics(client, args.url, stop, peaks)) if not args.no_metrics else None
        await asyncio.gather(*(stream_worker(w) for w in range(args.parallel)))
        wall_s = time.perf_counter() - t0
        stop.set()
        if poller:
            await poller
    return sorted(results, key=lambda r: r["start_s"]), wall_s, peaks


def print_table(results: list[dict]) -> None:
    print(f"{'stream':>6} {'seq':>3} {'start s':>8} {'TTFT ms':>9} {'prompt_ms':>9} {'queue ms':>9} "
          f"{'ITL p50':>8} {'ITL p95':>8} {'tokens':>6} {'total ms':>9}")
    for r in results:
        if "error" in r:
            print(f"{r['stream']:>6} {r['seq']:>3} {r['start_s']:>8.2f}  error: {r['error'][:80]}")
            continue
        num = lambda v, w: f"{v:>{w},.1f}" if v is not None else f"{'-':>{w}}"
        print(f"{r['stream']:>6} {r['seq']:>3} {r['start_s']:>8.2f} {num(r['ttft_ms'], 9)} {num(r['server_prompt_ms'], 9)} "
              f"{num(r['ttft_minus_prompt_ms'], 9)} {num(r['itl_p50_ms'], 8)} {num(r['itl_p95_ms'], 8)} "
              f"{r['content_chunks']:>6} {num(r['total_ms'], 9)}")


def print_summary(results: list[dict], wall_s: float, peaks: dict, parallel: int) -> None:
    ok = [r for r in results if "error" not in r]

    def col(key):
        return [r[key] for r in ok if r.get(key) is not None]

    def row(label, values):
        if not values:
            return
        print(f"  {label:<18}{fmt(pct(values, 50)):>11} {fmt(pct(values, 95)):>11} {fmt(max(values)):>11}")

    all_itl = [x for r in ok for x in r["itl_ms"]]
    tokens = sum(r["content_chunks"] for r in ok)
    print(f"\nsummary: {len(ok)}/{len(results)} ok, {parallel} parallel stream(s), wall {wall_s:,.1f} s")
    print(f"  {'':<18}{'p50':>11} {'p95':>11} {'max':>11}")
    row("TTFT", col("ttft_ms"))
    row("server prompt_ms", col("server_prompt_ms"))
    row("TTFT - prompt_ms", col("ttft_minus_prompt_ms"))
    row("ITL (all gaps)", all_itl)
    row("total", col("total_ms"))
    if ok:
        per_stream = [r["content_chunks"] / (r["total_ms"] - r["ttft_ms"]) * 1000
                      for r in ok if r["ttft_ms"] is not None and r["total_ms"] > r["ttft_ms"]]
        print(f"  throughput        {tokens / wall_s:,.1f} tok/s total"
              + (f", {statistics.fmean(per_stream):,.1f} tok/s per stream while generating" if per_stream else ""))
    if peaks.get("available"):
        print(f"  server /metrics   peak requests_processing={peaks.get('requests_processing', 0):.0f}, "
              f"peak requests_deferred={peaks.get('requests_deferred', 0):.0f}  (deferred > 0 = waiting for a slot)")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:18080", help="server base URL (no /v1)")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--prompt-file", help="read the prompt from a file (for long prompts)")
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--model", help="model name, if the server/router needs one")
    ap.add_argument("--parallel", "-np", type=int, default=1,
                    help="concurrent CLIENT streams (not server slots; compare with the server's -np)")
    ap.add_argument("--runs", type=int, default=1, help="requests per stream, back to back (total = parallel x runs)")
    ap.add_argument("--stagger", type=float, default=0.5,
                    help="streams 2..N start after a random 0..S s delay so they don't move in lockstep (0 = all at once)")
    ap.add_argument("--cache-prompt", action="store_true", help="allow prefix-cache reuse (default: cold prefill)")
    ap.add_argument("--no-metrics", action="store_true", help="don't poll /metrics during the run")
    ap.add_argument("--show-text", action="store_true", help="print the generated text (single stream only)")
    ap.add_argument("--json", action="store_true", help="one JSON line per request instead of the text report")
    args = ap.parse_args()
    if args.parallel < 1 or args.runs < 1:
        ap.error("--parallel and --runs must be >= 1")
    prompt = open(args.prompt_file).read() if args.prompt_file else args.prompt

    results, wall_s, peaks = await run_parallel(args, prompt)
    if args.json:
        return 0
    if args.parallel == 1:
        for i, r in enumerate(results, 1):
            if "error" in r:
                print(f"run {i}: error: {r['error']}")
                continue
            print_run(i, r)
            if args.show_text:
                print(f"  text: {r['text']!r}")
    else:
        print_table(results)
    if len(results) > 1:
        print_summary(results, wall_s, peaks, args.parallel)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except (httpx.HTTPError, RuntimeError) as exc:
        sys.exit(f"error: {exc}")
