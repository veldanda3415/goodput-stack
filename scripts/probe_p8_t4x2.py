#!/usr/bin/env python3
"""P8 on real GPUs: what a probe pays in first-token time on the replica full of long prompts (L) vs the one full
of short prompts (S). Kaggle 2×T4, real engines; routing not exercised.

Two vLLM servers of one model, one per GPU. No router: each condition drives a closed-loop background load per server
and sends probes straight to L or S ("forced to L / forced to S" in scripts/probe_p8_size_blind.py). Runs inside the
Kaggle stage `p8x2` (benchmarks/kaggle/t4_notebook.py); the stats and router functions below also run offline.

Background (per server, closed loop, exactly N workers): L = 2 long prompts, S = 3 short prompts (P8 shape: fewer
but heavier requests on L). Every prompt starts with a fresh uuid, prefix caching is off on the servers.
Prompt sizes are REAL tokens: P8's text ("<uuid> w0 w1 ...") cut to N tokens with the model's tokenizer. The sim
counted one token per word; Qwen's tokenizer splits the digits, so 3,000 such words would be ~14K tokens.

Probe: one unique short prompt, streamed with stream_options.include_usage, temperature 0, ignore_eos, max_tokens
128. Sent only after both servers have held their background in-flight count (running + waiting, minus our own
probe still on that server) for >= --hold-s, and >= --min-gap-s after the previous probe; one probe at a time.
Order: pairs of L/S, each pair in random order (seeded). Per probe: send time, TTFT (POST -> first non-empty
delta.content, as benchmarks/kaggle/t4_notebook.py chat()), every inter-token gap, e2e, usage, and both servers'
/metrics gauges just before the send. /metrics of both servers is sampled at 1 Hz for the whole run; every
background request is logged (send, first chunk, first content, end, usage, content bytes) so router inputs
that depend on dispatched requests can be rebuilt offline.

Offline: python scripts/probe_p8_t4x2.py --analyze benchmarks/results/t4/<run>_p8x2
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import random
import re
import statistics
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from benchmarks.harness.stats import pct  # noqa: E402  (linear interpolation, same as the harness)

GAUGES = {"running": "vllm:num_requests_running", "waiting": "vllm:num_requests_waiting",
          "kv": "vllm:kv_cache_usage_perc"}
COUNTERS = {"prompt_tokens": "vllm:prompt_tokens_total", "generation_tokens": "vllm:generation_tokens_total",
            "ttft_sum": "vllm:time_to_first_token_seconds_sum", "ttft_count": "vllm:time_to_first_token_seconds_count",
            "itl_sum": "vllm:inter_token_latency_seconds_sum", "itl_count": "vllm:inter_token_latency_seconds_count",
            "preemptions": "vllm:num_preemptions_total"}
METRIC_LINE = re.compile(r"^([a-zA-Z_:][\w:]*)(?:\{[^}]*\})?\s+([-+0-9.eE]+|NaN|\+Inf|-Inf)\s*$", re.M)
LABEL = "Kaggle 2×T4, real engines; routing not exercised"


# ---------------------------------------------------------------- pure helpers (unit-tested, no GPU)

def parse_metrics(text: str) -> dict[str, float]:
    """Selected vLLM metrics from a Prometheus text scrape, summed over label sets (one model per server)."""
    want = {v: k for k, v in (GAUGES | COUNTERS).items()}
    out: dict[str, float] = {}
    for name, val in METRIC_LINE.findall(text):
        if name in want:
            out[want[name]] = out.get(want[name], 0.0) + float(val)
    return out


def gaps(times: list[float]) -> list[float]:
    """Successive differences of chunk arrival times (inter-token gaps when one chunk = one token)."""
    return [b - a for a, b in zip(times, times[1:])]


def dist(values: list[float], nd: int = 4) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "p50": pct(values, 50), "p95": pct(values, 95), "max": round(max(values), nd),
            "min": round(min(values), nd), "mean": round(statistics.fmean(values), nd),
            "p25": pct(values, 25), "p75": pct(values, 75)}


def probe_order(n_per_server: int, seed: int, servers=("L", "S")) -> list[str]:
    """n pairs, each pair in random order: balanced over time, unpredictable within a pair."""
    rng = random.Random(seed)
    out: list[str] = []
    for _ in range(n_per_server):
        pair = list(servers)
        rng.shuffle(pair)
        out += pair
    return out


def bootstrap_median_diff(a: list[float], b: list[float], n: int = 5000, seed: int = 0) -> tuple[float, float] | None:
    """95 % percentile-bootstrap interval of median(a) - median(b)."""
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    d = sorted(statistics.median(rng.choices(a, k=len(a))) - statistics.median(rng.choices(b, k=len(b)))
               for _ in range(n))
    return round(d[int(0.025 * n)], 4), round(d[min(n - 1, int(0.975 * n))], 4)


def window(samples: list[dict], t0: float, t1: float, server: str | None = None) -> list[dict]:
    return [s for s in samples if t0 <= s["t"] <= t1 and (server is None or s.get("server") == server)]


def gauge_means(samples: list[dict]) -> dict:
    out: dict = {"n_samples": len(samples)}
    for k in GAUGES:
        vals = [s[k] for s in samples if k in s]
        if vals:
            out[f"{k}_mean"] = round(statistics.fmean(vals), 4)
            out[f"{k}_max"] = max(vals)
    return out


def counter_rate(samples: list[dict], key: str) -> float | None:
    """(last - first) / dt of a counter over time-ordered samples of one server."""
    s = [x for x in samples if key in x]
    if len(s) < 2 or s[-1]["t"] <= s[0]["t"]:
        return None
    return round((s[-1][key] - s[0][key]) / (s[-1]["t"] - s[0]["t"]), 2)


def gpu_window(csv_path: Path, t0: float, t1: float) -> dict:
    """Mean/max SM clock, util, power of one gpu_sampler CSV between two unix times."""
    if not Path(csv_path).exists():
        return {}
    with open(csv_path) as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error") and t0 <= float(r["t_unix"]) <= t1]
    out: dict = {"gpu_samples": len(rows)}
    for col in ("sm_clock_mhz", "util_gpu_pct", "power_w", "mem_used_mib", "temp_c"):
        vals = [float(r[col]) for r in rows if r.get(col) not in (None, "")]
        if vals:
            out[f"{col}_mean"] = round(statistics.fmean(vals), 1)
            out[f"{col}_max"] = max(vals)
            out[f"{col}_min"] = min(vals)
    return out


def est_tokens(content_bytes: int, role: str = "user") -> int:
    """llm-d-router v0.9.0 estimate backend: (len(role) + len(content)) bytes, zero-padded to 4, / 4
    (pkg/epp/framework/plugins/requestcontrol/dataproducer/tokenizer/estimate.go:35, 148-153, 248-258)."""
    return math.ceil((len(role.encode()) + content_bytes) / 4)


def token_load_at(bg: list[dict], server: str, t: float, use: str = "est_tokens") -> int:
    """In-flight prompt tokens a token-load scorer would hold for `server` at unix time t: requests dispatched before t
    whose first response chunk had not arrived by t (inflight-load-producer, addEstimatedOutputTokens=false, releases
    tokens on StartOfStream: dataproducer/inflightload/producer.go:420-431)."""
    tot = 0
    for r in bg:
        if r["server"] != server or r["t_send"] > t:
            continue
        first = r.get("t_first_chunk")
        if first is None or first > t:
            if first is None and r.get("t_end") is not None and r["t_end"] <= t:
                continue   # finished without a chunk (error): not in flight
            tot += int(r.get(use) or 0)
    return tot


def router_scores(snap: dict[str, dict], weights: dict | None = None, token_load: dict[str, float] | None = None,
                  threshold: float = 8192) -> dict:
    """Stock sim-pool profile (queue x2, kv-cache x2, prefix x3, max-score-picker) applied to real gauges, llm-d-router
    v0.9.0. Scores per endpoint, clamped to [0,1], times weight, summed (scheduling/scheduler_profile.go:178, 215-223):
      queue  = (max_w - w) / (max_w - min_w), 1.0 for all if equal    (scorer/queuedepth/queue.go:94-100)
      kv     = 1 - kv_cache_usage_perc                                  (scorer/kvcacheutilization/kvcache_utilization.go:79)
      prefix = matched / total blocks; unique prompts -> 0 everywhere  (scorer/prefix/plugin.go:117-120)
      token  = 1 - min(tokens, thr) / thr, 1.0 if tokens <= 0         (scorer/tokenload/token_load.go:115-123)
    max-score-picker: highest total wins, ties broken by a random shuffle (picker/maxscore/picker.go:91-102)."""
    w = weights or {"queue": 2.0, "kv": 2.0, "prefix": 3.0}
    eps = list(snap)
    waits = [snap[e]["waiting"] for e in eps]
    lo, hi = min(waits), max(waits)
    per: dict[str, dict] = {}
    for e in eps:
        s = {"queue": 1.0 if hi == lo else (hi - snap[e]["waiting"]) / (hi - lo),
             "kv": 1.0 - snap[e]["kv"], "prefix": 0.0}
        if token_load is not None and "token" in w:
            tl = token_load[e]
            s["token"] = 1.0 if tl <= 0 else 1.0 - min(tl, threshold) / threshold
        s = {k: min(1.0, max(0.0, v)) for k, v in s.items()}
        per[e] = {"scores": {k: round(v, 6) for k, v in s.items()},
                  "total": round(sum(v * w.get(k, 0.0) for k, v in s.items()), 6)}
    best = max(per[e]["total"] for e in eps)
    winners = [e for e in eps if per[e]["total"] == best]
    return {"per_endpoint": per, "pick": winners[0] if len(winners) == 1 else "tie",
            "margin": round(best - min(per[e]["total"] for e in eps), 6), "weights": w}


def make_prompt_body(tokenizer, n_tokens: int) -> str:
    """P8's prompt text ("w0 w1 ...") cut to n_tokens real tokens; a uuid is prepended per request."""
    words = " ".join(f"w{i}" for i in range(n_tokens))
    ids = tokenizer.encode(words, add_special_tokens=False)[:n_tokens]
    return tokenizer.decode(ids)


def unique_prompt(body: str) -> str:
    return f"{uuid.uuid4().hex} {body}"


# ---------------------------------------------------------------- async client (inside the Kaggle stage)

async def stream_chat(c, url: str, model: str, prompt: str, max_tokens: int) -> dict:
    """Streamed /v1/chat/completions; TTFT = POST -> first chunk with non-empty delta.content."""
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0.0, "ignore_eos": True, "stream": True, "stream_options": {"include_usage": True}}
    rec: dict = {"content_bytes": len(prompt.encode()), "max_tokens": max_tokens}
    rec["est_tokens"] = est_tokens(rec["content_bytes"])
    times: list[float] = []
    usage = None
    rec["t_send"] = time.time()
    t0 = time.perf_counter()
    try:
        async with c.stream("POST", url + "/v1/chat/completions", json=body, timeout=900) as r:
            rec["status"] = r.status_code
            if r.status_code != 200:
                rec["error"] = (await r.aread()).decode(errors="replace")[:300]
            else:
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    if "t_first_chunk" not in rec:
                        rec["t_first_chunk"] = rec["t_send"] + (time.perf_counter() - t0)
                    if line == "data: [DONE]":
                        continue
                    j = json.loads(line[6:])
                    if j.get("usage"):
                        usage = j["usage"]
                    for ch in j.get("choices") or []:
                        if (ch.get("delta") or {}).get("content"):
                            times.append(time.perf_counter())
    except Exception as exc:   # recorded, never retried silently
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    t_end = time.perf_counter()
    rec["t_end"] = rec["t_send"] + (t_end - t0)
    rec["e2e_s"] = round(t_end - t0, 4)
    rec["usage"] = usage
    rec["prompt_tokens"] = (usage or {}).get("prompt_tokens")
    rec["completion_tokens"] = (usage or {}).get("completion_tokens")
    rec["content_chunks"] = len(times)
    if times:
        rec["ttft_s"] = round(times[0] - t0, 4)
        rec["t_first_content"] = rec["t_send"] + (times[0] - t0)
        rec["itl_s"] = [round(g, 5) for g in gaps(times)]
    return rec


async def scrape(c, url: str) -> dict:
    t = time.time()
    try:
        r = await c.get(url + "/metrics", timeout=5)
        return {"t": t, **parse_metrics(r.text)}
    except Exception as exc:
        return {"t": t, "error": f"{type(exc).__name__}: {exc}"[:200]}


class Run:
    """State shared by the background workers, the 1 Hz sampler and the probe loop of one stage run."""

    def __init__(self, servers: dict[str, str], model: str, out_dir: Path, bodies: dict[int, str]):
        self.servers, self.model, self.out = servers, model, out_dir
        self.bodies = bodies   # prompt tokens -> body text
        self.out.mkdir(parents=True, exist_ok=True)
        self.bg_f = open(out_dir / "background.jsonl", "a")
        self.probe_f = open(out_dir / "probes.jsonl", "a")
        self.metrics_f = open(out_dir / "metrics_1hz.jsonl", "a")
        self.active_probe: dict[str, int] = {k: 0 for k in servers}
        self.condition = "setup"
        self.latest: dict[str, dict] = {}

    def body(self, n_tokens: int) -> str:
        return self.bodies[n_tokens]

    async def sampler(self, c, stop: asyncio.Event, interval: float = 1.0) -> None:
        nxt = time.monotonic()
        while not stop.is_set():
            snaps = await asyncio.gather(*(scrape(c, u) for u in self.servers.values()))
            for name, s in zip(self.servers, snaps):
                s |= {"server": name, "condition": self.condition}
                self.latest[name] = s
                self.metrics_f.write(json.dumps(s) + "\n")
            self.metrics_f.flush()
            nxt += interval
            try:
                await asyncio.wait_for(stop.wait(), max(0.0, nxt - time.monotonic()))
            except asyncio.TimeoutError:
                pass

    async def bg_worker(self, c, server: str, n_tokens: int, max_tokens: int, stop: asyncio.Event, wid: int) -> None:
        while not stop.is_set():
            rec = await stream_chat(c, self.servers[server], self.model, unique_prompt(self.body(n_tokens)), max_tokens)
            rec = {"condition": self.condition, "server": server, "worker": wid, "target_tokens": n_tokens,
                   **{k: v for k, v in rec.items() if k != "itl_s"}}
            self.bg_f.write(json.dumps(rec) + "\n")
            self.bg_f.flush()
            if rec.get("error"):
                await asyncio.sleep(1.0)   # a failing server must not spin

    async def gate(self, c, targets: dict[str, int], hold_s: float, timeout_s: float) -> dict:
        """Wait until every server's running+waiting (minus our active probe) == target for hold_s."""
        t0 = time.monotonic()
        held_since = None
        polls = resets = 0
        while True:
            snaps = await asyncio.gather(*(scrape(c, self.servers[s]) for s in targets))
            polls += 1
            ok = all("error" not in g and g.get("running", -1) + g.get("waiting", 0) - self.active_probe[s] == targets[s]
                     for s, g in zip(targets, snaps))
            now = time.monotonic()
            if ok:
                held_since = held_since or now
                if now - held_since >= hold_s:
                    return {"gate_ok": True, "gate_wait_s": round(now - t0, 2), "gate_polls": polls, "gate_resets": resets}
            elif held_since is not None:
                held_since, resets = None, resets + 1
            if now - t0 > timeout_s:
                return {"gate_ok": False, "gate_wait_s": round(now - t0, 2), "gate_polls": polls, "gate_resets": resets,
                        "gate_last": {s: {k: g.get(k) for k in ("running", "waiting")} for s, g in zip(targets, snaps)}}
            await asyncio.sleep(0.5)

    async def probe(self, c, server: str, probe_tokens: int, max_tokens: int, extra: dict) -> dict:
        snaps = await asyncio.gather(*(scrape(c, u) for u in self.servers.values()))
        pre = {name: {k: s.get(k) for k in ("t", "running", "waiting", "kv", "error") if k in s}
               for name, s in zip(self.servers, snaps)}
        self.active_probe[server] += 1
        try:
            rec = await stream_chat(c, self.servers[server], self.model, unique_prompt(self.body(probe_tokens)), max_tokens)
        finally:
            self.active_probe[server] -= 1
        rec = {"condition": self.condition, "server": server, "pre_metrics": pre, **extra, **rec}
        self.probe_f.write(json.dumps(rec) + "\n")
        self.probe_f.flush()
        return rec

    def close(self) -> None:
        for f in (self.bg_f, self.probe_f, self.metrics_f):
            f.close()


async def run_condition(run: Run, c, cond: dict, deadline_unix: float | None = None) -> dict:
    """One condition: start background, probe in a seeded L/S order, stop background. Returns the window + counts."""
    run.condition = cond["name"]
    stop = asyncio.Event()
    workers = []
    for server, (n, tokens) in cond["background"].items():
        for i in range(n):
            workers.append(asyncio.create_task(run.bg_worker(c, server, tokens, cond["bg_max_tokens"], stop, i)))
    targets = {s: cond["background"].get(s, (0, 0))[0] for s in run.servers}
    t_start = time.time()
    order = probe_order(cond["n"], cond["seed"], tuple(cond.get("probe_servers", ("L", "S"))))
    sent, last_send, stopped = 0, 0.0, None
    for i, server in enumerate(order):
        if deadline_unix and time.time() > deadline_unix:
            stopped = f"session budget reached after {sent} probes"
            break
        g = await run.gate(c, targets, cond["hold_s"], cond["gate_timeout_s"])
        wait = cond["min_gap_s"] - (time.time() - last_send)
        if wait > 0:
            await asyncio.sleep(wait)
        last_send = time.time()
        await run.probe(c, server, cond["probe_tokens"], cond["probe_max_tokens"],
                        {"probe_index": i, "targets": targets, **g})
        sent += 1
    t_probes_end = time.time()
    stop.set()
    for w in workers:   # in-flight background requests are cancelled; they are logged only when they finish
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    return {"condition": cond["name"], "t_start": t_start, "t_end": t_probes_end, "probes_sent": sent,
            "stopped_early": stopped, "targets": targets}


# ---------------------------------------------------------------- offline analysis

def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def summarize_condition(cond: dict, probes: list[dict], bg: list[dict], samples: list[dict], gpu_csvs: dict) -> dict:
    """Per server: probe TTFT/ITL/e2e, background tok/s, gauge means, GPU clocks; plus the L-S headline."""
    t0, t1 = cond["t_start"], cond["t_end"]
    out: dict = {"condition": cond["condition"], "window_s": round(t1 - t0, 1), "label": LABEL, "servers": {}}
    for s in ("L", "S"):
        pr = [p for p in probes if p["condition"] == cond["condition"] and p["server"] == s]
        ok = [p for p in pr if p.get("ttft_s") is not None and not p.get("error")]
        bgs = [b for b in bg if b["condition"] == cond["condition"] and b["server"] == s and not b.get("error")
               and t0 <= b["t_end"] <= t1]
        sm = window(samples, t0, t1, s)
        row = {"probes": len(pr), "probes_ok": len(ok), "probes_gate_failed": sum(1 for p in pr if not p.get("gate_ok", True)),
               "ttft_s": dist([p["ttft_s"] for p in ok]), "e2e_s": dist([p["e2e_s"] for p in ok]),
               "itl_s": dist([g for p in ok for g in p.get("itl_s", [])], 5),
               "probe_prompt_tokens": sorted({p.get("prompt_tokens") for p in ok}),
               "probe_completion_tokens": sorted({p.get("completion_tokens") for p in ok}),
               "bg_requests_done": len(bgs),
               "bg_prompt_tokens_mean": round(statistics.fmean([b["prompt_tokens"] for b in bgs if b.get("prompt_tokens")]), 1)
               if any(b.get("prompt_tokens") for b in bgs) else None,
               "bg_output_tok_s_client": round(sum(b.get("completion_tokens") or 0 for b in bgs) / (t1 - t0), 2) if t1 > t0 else None,
               "bg_prompt_tok_s_client": round(sum(b.get("prompt_tokens") or 0 for b in bgs) / (t1 - t0), 2) if t1 > t0 else None,
               "srv_generation_tok_s": counter_rate(sm, "generation_tokens"),
               "srv_prompt_tok_s": counter_rate(sm, "prompt_tokens"),
               "srv_preemptions": (sm[-1].get("preemptions", 0) - sm[0].get("preemptions", 0)) if len(sm) > 1 else None,
               **{f"gauge_{k}": v for k, v in gauge_means(sm).items()}}
        csv_path = gpu_csvs.get(s)
        if csv_path:
            row["gpu"] = gpu_window(csv_path, t0, t1)
        out["servers"][s] = row
    ttl = [p["ttft_s"] for p in probes if p["condition"] == cond["condition"] and p["server"] == "L" and p.get("ttft_s") is not None]
    tts = [p["ttft_s"] for p in probes if p["condition"] == cond["condition"] and p["server"] == "S" and p.get("ttft_s") is not None]
    if ttl and tts:
        ml, ms = statistics.median(ttl), statistics.median(tts)
        out["headline"] = {"median_ttft_L_s": round(ml, 4), "median_ttft_S_s": round(ms, 4), "gap_s": round(ml - ms, 4),
                           "ratio": round(ml / ms, 2) if ms else None, "gap_ci95_bootstrap_s": bootstrap_median_diff(ttl, tts),
                           "n_L": len(ttl), "n_S": len(tts)}
    return out


def router_table(probes: list[dict], bg: list[dict], condition: str) -> dict:
    """Per probe: stock-profile scores from the pre-send /metrics snapshots, and token-load profile scores with the
    dispatched-token load rebuilt from the background log (computed offline from real engine metrics)."""
    rows = []
    for p in probes:
        if p["condition"] != condition:
            continue
        pre = p["pre_metrics"]
        if any("error" in pre[s] or pre[s].get("waiting") is None for s in ("L", "S")):
            continue
        snap = {s: {"waiting": pre[s]["waiting"], "kv": pre[s]["kv"], "running": pre[s]["running"]} for s in ("L", "S")}
        stock = router_scores(snap)
        t = p["t_send"]
        tl_est = {s: token_load_at(bg, s, t, "est_tokens") for s in ("L", "S")}
        tl_real = {s: token_load_at(bg, s, t, "prompt_tokens") for s in ("L", "S")}
        tok = router_scores(snap, {"queue": 2.0, "kv": 2.0, "prefix": 3.0, "token": 4.0}, tl_est)
        rows.append({"probe_index": p["probe_index"], "probe_server": p["server"], "snap": snap,
                     "stock": stock, "token_load_est": tl_est, "token_load_real_tokens": tl_real, "token_profile": tok})
    picks = [r["stock"]["pick"] for r in rows]
    tpicks = [r["token_profile"]["pick"] for r in rows]
    return {"condition": condition, "n": len(rows), "label": "computed offline from real engine metrics",
            "stock_picks": {k: picks.count(k) for k in ("L", "S", "tie")},
            "stock_margin_median": statistics.median([r["stock"]["margin"] for r in rows]) if rows else None,
            "token_picks": {k: tpicks.count(k) for k in ("L", "S", "tie")}, "rows": rows}


def analyze(run_dir: Path) -> dict:
    d = run_dir / "results" / "p8x2" if (run_dir / "results" / "p8x2").is_dir() else run_dir
    probes, bg = read_jsonl(d / "probes.jsonl"), read_jsonl(d / "background.jsonl")
    samples = [s for s in read_jsonl(d / "metrics_1hz.jsonl") if "error" not in s]
    conds = [r for r in read_jsonl(d / "p8x2.jsonl") if r.get("kind") == "condition_window"]
    gpu = {"L": d / "gpu0.csv", "S": d / "gpu1.csv"}
    return {"conditions": [summarize_condition(c, probes, bg, samples, gpu) for c in conds],
            "router": [router_table(probes, bg, c["condition"]) for c in conds]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analyze", type=Path, required=True, help="run dir of a p8x2 stage (or its results/p8x2/)")
    a = ap.parse_args()
    res = analyze(a.analyze)
    for c in res["conditions"]:
        print(json.dumps({k: v for k, v in c.items() if k != "servers"}))
        for s, row in c["servers"].items():
            print(f"  {s}: ttft {row['ttft_s']} itl p50/p95 {row['itl_s'].get('p50')}/{row['itl_s'].get('p95')} "
                  f"running {row.get('gauge_running_mean')} waiting {row.get('gauge_waiting_mean')} kv {row.get('gauge_kv_mean')}")
    for r in res["router"]:
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}))


if __name__ == "__main__":
    main()
