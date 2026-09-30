"""Async streaming load client (httpx) + background /metrics and /slots sampler.

Timing model per request (all client-side, monotonic clock):
    ttft  = first streamed token chunk - request sent
    itl   = gaps between consecutive token chunks
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

async def make_prompts(client: httpx.AsyncClient, n: int, n_tokens: int, seed: int = 0) -> list[str]:
    """Build n unique prompts of ~exactly n_tokens (calibrated with the server tokenizer)."""
    rng = random.Random(seed)
    prompts = []
    for _ in range(n):
        # Unique prefix defeats prefix caching even if cache_prompt were left on.
        words = [f"[{uuid.uuid4().hex[:8]}]"] + [rng.choice(FILLER_WORDS) for _ in range(n_tokens * 2 + 16)]
        text = " ".join(words)
        toks = (await client.post("/tokenize", json={"content": text})).json()["tokens"][:n_tokens]
        prompts.append((await client.post("/detokenize", json={"tokens": toks})).json()["content"])
    return prompts


# ---------------------------------------------------------------- one request

async def one_request(client: httpx.AsyncClient, c: dict, prompt: str, req_id: int, worker: int) -> dict:
    body = {
        "prompt": prompt,
        "n_predict": c["max_tokens"],
        "ignore_eos": c["ignore_eos"],
        "temperature": c["temperature"],
        "cache_prompt": c["cache_prompt"],
        "stream": True,
    }
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
                chunk = json.loads(line[6:])
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
    rec["t_start_rel"] = t0
    rec["t_end_rel"] = t_end
    return rec


# ---------------------------------------------------------------- load

async def run_load(base_url: str, c: dict) -> tuple[list[dict], float]:
    """Warmup sequentially, then `requests` via `concurrency` closed-loop workers."""
    limits = httpx.Limits(max_connections=c["concurrency"] + 4)
    async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=c["timeout_s"]) as client:
        total = c["warmup"] + c["requests"]
        prompts = await make_prompts(client, total, c["prompt_tokens"])

        for i in range(c["warmup"]):
            await one_request(client, c, prompts[i], -1 - i, worker=-1)

        queue: asyncio.Queue = asyncio.Queue()
        for i in range(c["requests"]):
            queue.put_nowait((i, prompts[c["warmup"] + i]))
        records: list[dict] = []

        async def worker(w: int) -> None:
            while True:
                try:
                    i, prompt = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                records.append(await one_request(client, c, prompt, i, w))

        t0 = time.monotonic()
        await asyncio.gather(*(worker(w) for w in range(c["concurrency"])))
        wall_s = time.monotonic() - t0

    for r in records:  # make start/end relative to the measured window
        for k in ("t_start_rel", "t_end_rel"):
            if k in r:
                r[k] = round(r[k] - t0, 4)
    return sorted(records, key=lambda r: r["id"]), wall_s


# ---------------------------------------------------------------- metrics sampler

def parse_prometheus(text: str) -> dict[str, float]:
    out = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        try:
            out[name.removeprefix("llamacpp:")] = float(value)
        except ValueError:
            pass
    return out


async def scrape(client: httpx.AsyncClient) -> dict:
    sample = {"t_unix": time.time(), "t_mono": time.monotonic()}
    try:
        sample["metrics"] = parse_prometheus((await client.get("/metrics")).text)
    except httpx.HTTPError as exc:
        sample["error"] = str(exc)
    try:
        slots = (await client.get("/slots")).json()
        sample["slots_busy"] = sum(1 for s in slots if s.get("is_processing"))
        sample["slots_total"] = len(slots)
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return sample


async def sample_metrics(base_url: str, interval_s: float, stop: asyncio.Event) -> list[dict]:
    samples: list[dict] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        while not stop.is_set():
            samples.append(await scrape(client))
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass
        samples.append(await scrape(client))
    return samples


async def idle_probe(base_url: str) -> list[dict]:
    """Two scrapes with no traffic: shows whether gauges are windowed (reset on scrape)."""
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        first = await scrape(client)
        await asyncio.sleep(1.0)
        second = await scrape(client)
    return [first, second]


async def run_point(base_url: str, cfg: dict) -> dict:
    stop = asyncio.Event()
    interval = cfg["metrics"]["scrape_interval_s"]
    sampler = asyncio.create_task(sample_metrics(base_url, interval, stop)) if interval else None
    try:
        records, wall_s = await run_load(base_url, cfg["client"])
    finally:
        stop.set()
        samples = await sampler if sampler else []
    return {"records": records, "wall_s": wall_s, "samples": samples, "idle_probe": await idle_probe(base_url)}
