"""Async streaming load client (httpx) + background /metrics and /slots sampler.

Two wire APIs (`client.api`):
    llamacpp  POST /completion (n_predict, cache_prompt), /tokenize + /detokenize, /slots;
              server `timings` (prompt_ms, ...) in the final chunk
    openai    POST /v1/completions (vLLM, llm-d-inference-sim): `model` required, `usage` via
              stream_options; vLLM's /tokenize (count only, no /detokenize); no /slots

Timing model per request (all client-side, monotonic clock):
    ttft  = first streamed token chunk - request sent
    itl   = gaps between consecutive token chunks
    tpot  = (last token - first token) / (tokens - 1)   (per-request mean ITL)
    e2e   = final chunk - request sent
Server-side `timings` from the final chunk are stored alongside for comparison.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid

import httpx

FILLER_WORDS = (
    "network latency packet switch router kernel cluster tensor matrix vector cache "
    "memory bandwidth thread schedule queue token context model server client stream "
    "buffer socket signal index record policy region channel window object"
).split()


# ---------------------------------------------------------------- prompts

async def make_prompts(client: httpx.AsyncClient, n: int, c: dict, seed: int = 0) -> list[str]:
    """Build n unique prompts of ~exactly c["prompt_tokens"] (calibrated with the server tokenizer)."""
    rng = random.Random(seed)
    n_tokens = c["prompt_tokens"]
    prompts = []
    for _ in range(n):
        # Unique prefix defeats prefix caching even if cache_prompt were left on.
        words = [f"[{uuid.uuid4().hex[:8]}]"] + [rng.choice(FILLER_WORDS) for _ in range(n_tokens * 2 + 16)]
        if c.get("api") == "openai":
            prompts.append(await fit_words(client, c["model"], words, n_tokens))
            continue
        text = " ".join(words)
        toks = (await client.post("/tokenize", json={"content": text})).json()["tokens"][:n_tokens]
        prompts.append((await client.post("/detokenize", json={"tokens": toks})).json()["content"])
    return prompts


async def count_tokens(client: httpx.AsyncClient, model: str, text: str) -> int:
    r = await client.post("/tokenize", json={"model": model, "prompt": text, "add_special_tokens": False})
    r.raise_for_status()
    return r.json()["count"]


async def fit_words(client: httpx.AsyncClient, model: str, words: list[str], n_tokens: int) -> str:
    """Longest word prefix with <= n_tokens tokens (vLLM-style servers have no /detokenize).
    Filler words are ~1 token each, so stepping by the miss converges in 1-3 calls."""
    k, best = min(n_tokens, len(words)), 1
    for _ in range(12):
        count = await count_tokens(client, model, " ".join(words[:k]))
        if count <= n_tokens:
            best = max(best, k)
        if count == n_tokens:
            break
        nxt = max(1, min(len(words), k + n_tokens - count))
        if nxt == k:
            break
        k = nxt
    return " ".join(words[:best])


# ---------------------------------------------------------------- one request

def request_body(c: dict, prompt: str, max_tokens: int) -> dict:
    if c.get("api") == "openai":
        return {"model": c["model"], "prompt": prompt, "max_tokens": max_tokens, "ignore_eos": c["ignore_eos"],
                "temperature": c["temperature"], "stream": True, "stream_options": {"include_usage": True}}
    return {"prompt": prompt, "n_predict": max_tokens, "ignore_eos": c["ignore_eos"],
            "temperature": c["temperature"], "cache_prompt": c["cache_prompt"], "stream": True}


async def one_request(client: httpx.AsyncClient, c: dict, prompt: str, req_id: int, worker: int,
                      max_tokens: int | None = None) -> dict:
    body = request_body(c, prompt, max_tokens or c["max_tokens"])
    openai = c.get("api") == "openai"
    rec = {"id": req_id, "worker": worker, "ok": False, "t_send_unix": time.time()}
    token_times: list[float] = []
    t0 = time.monotonic()
    try:
        async with client.stream("POST", c["endpoint"], json=body, timeout=c["timeout_s"]) as resp:
            rec["status"] = resp.status_code
            if resp.status_code != 200:
                rec["error"] = (await resp.aread()).decode(errors="replace")[:500]
                return rec
            t_first_byte = None
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                now = time.monotonic()
                t_first_byte = t_first_byte or now
                if line == "data: [DONE]":
                    break
                chunk = json.loads(line[6:])
                if openai:
                    # One chunk per token; the finish chunk may be empty (sim) or carry the last
                    # token (vLLM); the usage chunk has no choices.
                    if chunk.get("usage"):
                        rec["usage"] = chunk["usage"]
                    for ch in chunk.get("choices") or []:
                        if ch.get("text") or ch.get("finish_reason") is None:
                            token_times.append(now)
                        if ch.get("finish_reason"):
                            rec["stop_type"] = ch["finish_reason"]
                    continue
                if chunk.get("stop"):
                    rec["timings"] = chunk.get("timings", {})
                    rec["tokens_evaluated"] = chunk.get("tokens_evaluated")
                    rec["stop_type"] = chunk.get("stop_type")
                    break
                token_times.append(now)  # one non-final chunk per generated token
        t_end = time.monotonic()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec

    rec["ok"] = bool(token_times)
    rec["n_tokens"] = len(token_times)
    rec["ttfb_ms"] = round((t_first_byte - t0) * 1e3, 3) if t_first_byte else None
    rec["ttft_ms"] = round((token_times[0] - t0) * 1e3, 3) if token_times else None
    rec["e2e_ms"] = round((t_end - t0) * 1e3, 3)
    rec["itl_ms"] = [round((b - a) * 1e3, 3) for a, b in zip(token_times, token_times[1:])]
    # TPOT: mean time per output token after the first (the per-user "reading speed").
    rec["tpot_ms"] = round((token_times[-1] - token_times[0]) * 1e3 / (len(token_times) - 1), 3) if len(token_times) > 1 else None
    rec["t_start_rel"] = t0
    rec["t_end_rel"] = t_end
    rec["_token_times"] = token_times  # absolute; used for the steady window, then dropped
    return rec


# ---------------------------------------------------------------- load

def output_lengths(c: dict, n: int, seed: int = 1) -> list[int]:
    """Per-request max_tokens: fixed, or uniform in max_tokens x (1 +/- max_tokens_jitter)."""
    j = c.get("max_tokens_jitter") or 0
    if not j:
        return [c["max_tokens"]] * n
    rng = random.Random(seed)
    lo, hi = max(1, round(c["max_tokens"] * (1 - j))), round(c["max_tokens"] * (1 + j))
    return [rng.randint(lo, hi) for _ in range(n)]


def steady_window(records: list[dict]) -> tuple[float, float] | None:
    """[last worker's first send, first worker's last finish]: every worker is busy inside it."""
    by_worker: dict[int, list[dict]] = {}
    for r in records:
        if "t_start_rel" in r:
            by_worker.setdefault(r["worker"], []).append(r)
    if not by_worker:
        return None
    start = max(min(r["t_start_rel"] for r in rs) for rs in by_worker.values())
    end = min(max(r["t_end_rel"] for r in rs) for rs in by_worker.values())
    return (start, end) if end > start else None


async def run_load(base_url: str, c: dict) -> tuple[list[dict], float, dict, dict]:
    """Warmup sequentially, then measured requests via `concurrency` closed-loop workers.

    Request count: `requests`, or concurrency x `requests_per_client` if set, never below
    `min_requests`. De-synchronisation (so clients don't move in lockstep): each worker
    starts after a random delay in [0, start_jitter_s], and per-request output length
    varies by +/- max_tokens_jitter. Also returns a /metrics scrape taken after warmup, so
    server-side counter deltas cover only the measured requests.
    """
    n_requests = c["concurrency"] * c["requests_per_client"] if c.get("requests_per_client") else c["requests"]
    n_requests = max(n_requests, c.get("min_requests") or 0)
    lengths = output_lengths(c, n_requests)
    rng = random.Random(2)
    delays = [rng.uniform(0, c.get("start_jitter_s") or 0) for _ in range(c["concurrency"])]
    limits = httpx.Limits(max_connections=c["concurrency"] + 4)
    async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=c["timeout_s"]) as client:
        total = c["warmup"] + n_requests
        prompts = await make_prompts(client, total, c)

        for i in range(c["warmup"]):
            await one_request(client, c, prompts[i], -1 - i, worker=-1)
        baseline = await scrape(client, slots=False)

        queue: asyncio.Queue = asyncio.Queue()
        for i in range(n_requests):
            queue.put_nowait((i, prompts[c["warmup"] + i], lengths[i]))
        records: list[dict] = []

        async def worker(w: int) -> None:
            await asyncio.sleep(delays[w])
            while True:
                try:
                    i, prompt, n_tok = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                records.append(await one_request(client, c, prompt, i, w, max_tokens=n_tok))

        t0 = time.monotonic()
        await asyncio.gather(*(worker(w) for w in range(c["concurrency"])))
        wall_s = time.monotonic() - t0

    for r in records:  # make start/end relative to the measured window
        for k in ("t_start_rel", "t_end_rel"):
            if k in r:
                r[k] = round(r[k] - t0, 4)

    steady: dict = {}
    window = steady_window(records)
    if window:
        ws, we = window
        tokens = sum(1 for r in records for t in r.get("_token_times", []) if ws <= t - t0 <= we)
        steady = {"steady_s": round(we - ws, 3), "steady_output_tok_s": round(tokens / (we - ws), 2)}
        for r in records:
            r["in_steady"] = "t_start_rel" in r and r["t_start_rel"] >= ws and r["t_end_rel"] <= we
    for r in records:
        r.pop("_token_times", None)
    return sorted(records, key=lambda r: r["id"]), wall_s, steady, baseline


# ---------------------------------------------------------------- metrics sampler

def parse_prometheus(text: str) -> dict[str, float]:
    """name -> value with the `llamacpp:` / `vllm:` prefix dropped. Label sets are summed
    (vLLM labels by model_name, finish_reason); histogram buckets are skipped (_sum/_count kept)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        name = name.split("{", 1)[0]
        if name.endswith("_bucket"):
            continue
        try:
            key = name.removeprefix("llamacpp:").removeprefix("vllm:")
            out[key] = out.get(key, 0.0) + float(value)
        except ValueError:
            pass
    return out


async def scrape(client: httpx.AsyncClient, slots: bool = True) -> dict:
    sample = {"t_unix": time.time(), "t_mono": time.monotonic()}
    try:
        sample["metrics"] = parse_prometheus((await client.get("/metrics")).text)
    except httpx.HTTPError as exc:
        sample["error"] = str(exc)
    if not slots:
        return sample
    try:
        slots = (await client.get("/slots")).json()
        sample["slots_busy"] = sum(1 for s in slots if s.get("is_processing"))
        sample["slots_total"] = len(slots)
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return sample


async def sample_metrics(base_url: str, interval_s: float, stop: asyncio.Event, slots: bool) -> list[dict]:
    samples: list[dict] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        while not stop.is_set():
            samples.append(await scrape(client, slots))
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass
        samples.append(await scrape(client, slots))
    return samples


async def idle_probe(base_url: str, slots: bool) -> list[dict]:
    """Two scrapes with no traffic: shows whether gauges are windowed (reset on scrape)."""
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        first = await scrape(client, slots)
        await asyncio.sleep(1.0)
        second = await scrape(client, slots)
    return [first, second]


async def run_point(base_url: str, cfg: dict) -> dict:
    stop = asyncio.Event()
    interval = cfg["metrics"]["scrape_interval_s"]
    slots = cfg["client"].get("api", "llamacpp") == "llamacpp"   # /slots is llama.cpp-only
    sampler = asyncio.create_task(sample_metrics(base_url, interval, stop, slots)) if interval else None
    try:
        records, wall_s, steady, baseline = await run_load(base_url, cfg["client"])
    finally:
        stop.set()
        samples = await sampler if sampler else []
    return {"records": records, "wall_s": wall_s, "steady": steady, "samples": samples,
            "baseline": baseline, "idle_probe": await idle_probe(base_url, slots)}
