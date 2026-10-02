"""Turn raw per-request records and /metrics samples into a flat summary row."""

from __future__ import annotations

import statistics


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def dist(prefix: str, values: list[float]) -> dict:
    if not values:
        return {}
    return {
        f"{prefix}_mean": round(statistics.fmean(values), 3),
        f"{prefix}_p50": pct(values, 50),
        f"{prefix}_p95": pct(values, 95),
        f"{prefix}_p99": pct(values, 99),
        f"{prefix}_max": round(max(values), 3),
    }


def meets_slo(r: dict, slo: dict) -> bool:
    if not r.get("ok"):
        return False
    if slo.get("ttft_ms") is not None and r["ttft_ms"] > slo["ttft_ms"]:
        return False
    if slo.get("tpot_ms") is not None and (r.get("tpot_ms") or 0) > slo["tpot_ms"]:
        return False
    return True


def summarize_load(result: dict, slo: dict | None = None) -> dict:
    recs = result["records"]
    ok = [r for r in recs if r.get("ok")]
    out_tokens = sum(r["n_tokens"] for r in ok)
    timings = [r.get("timings", {}) for r in ok]
    usage = [r["usage"] for r in ok if r.get("usage")]   # OpenAI API: no timings, usage instead
    if usage:
        prompt_n = [u.get("prompt_tokens", 0) for u in usage]
        cache_n = [(u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) for u in usage]
    else:
        prompt_n = [t.get("prompt_n", 0) for t in timings]
        cache_n = [t.get("cache_n", 0) for t in timings]
    row = {
        "requests_ok": len(ok),
        "requests_failed": len(recs) - len(ok),
        "wall_s": round(result["wall_s"], 3),
        "agg_output_tok_s": round(out_tokens / result["wall_s"], 2) if result["wall_s"] else None,
        **result.get("steady", {}),
        "prompt_n_mean": round(statistics.fmean(prompt_n), 1) if prompt_n else None,
        "cache_n_mean": round(statistics.fmean(cache_n), 1) if cache_n else None,
    }
    if usage:
        # streamed token chunks vs the server's own completion_tokens: should always be 0
        row["usage_token_mismatch"] = sum(1 for r in ok if r.get("usage") and
                                          r["usage"].get("completion_tokens") != r["n_tokens"])
    row |= dist("ttft_ms", [r["ttft_ms"] for r in ok])
    row |= dist("e2e_ms", [r["e2e_ms"] for r in ok])
    row |= dist("itl_ms", [x for r in ok for x in r["itl_ms"]])
    row |= dist("tpot_ms", [r["tpot_ms"] for r in ok if r.get("tpot_ms") is not None])
    if slo and (slo.get("ttft_ms") is not None or slo.get("tpot_ms") is not None):
        good = [r for r in recs if meets_slo(r, slo)]
        row["slo_attainment_pct"] = round(100 * len(good) / len(recs), 1) if recs else None
        # Goodput: only tokens from requests that met the SLO count.
        row["goodput_tok_s"] = round(sum(r["n_tokens"] for r in good) / result["wall_s"], 2) if result["wall_s"] else None
    row |= dist("srv_prompt_ms", [t["prompt_ms"] for t in timings if "prompt_ms" in t])
    # Client TTFT minus server prefill time = HTTP + queueing + first decode step.
    row |= dist("ttft_minus_srv_prompt_ms", [
        r["ttft_ms"] - r["timings"]["prompt_ms"] for r in ok if "prompt_ms" in r.get("timings", {})
    ])
    decode = [t["predicted_per_second"] for t in timings if t.get("predicted_per_second")]
    row["srv_decode_tok_s_mean"] = round(statistics.fmean(decode), 2) if decode else None
    row |= summarize_metrics(result["samples"], result["idle_probe"], result.get("baseline"))
    if row.get("m_srv_ttft_ms_mean") is not None and row.get("ttft_ms_mean") is not None:
        # client TTFT minus the server's own TTFT histogram = HTTP + Service path + streaming
        row["ttft_minus_srv_ttft_ms_mean"] = round(row["ttft_ms_mean"] - row["m_srv_ttft_ms_mean"], 3)
    return row


# Same meaning, different names: llama.cpp first, vLLM second (prefixes already stripped).
QUEUED = ("requests_deferred", "num_requests_waiting")
RUNNING = ("requests_processing", "num_requests_running")
GENERATED = ("tokens_predicted_total", "generation_tokens_total")

# vLLM histograms -> mean over the measured requests from _sum/_count deltas (baseline = after warmup)
VLLM_HISTOGRAMS = {
    "time_to_first_token_seconds": "m_srv_ttft_ms_mean",
    "request_queue_time_seconds": "m_srv_queue_ms_mean",
    "request_prefill_time_seconds": "m_srv_prefill_ms_mean",
    "inter_token_latency_seconds": "m_srv_itl_ms_mean",
    "time_per_output_token_seconds": "m_srv_tpot_ms_mean",
    "request_decode_time_seconds": "m_srv_decode_ms_mean",
    "e2e_request_latency_seconds": "m_srv_e2e_ms_mean",
}


def _get(m: dict, names: tuple[str, ...]) -> float:
    return next((m[n] for n in names if n in m), 0)


def summarize_metrics(samples: list[dict], idle: list[dict], baseline: dict | None = None) -> dict:
    """Compare the /metrics gauges against rates derived from counter deltas.

    gauge predicted_tokens_seconds        : what llama.cpp reports
    counter tokens/tokens_seconds deltas  : per-slot decode speed (time summed across slots)
    counter tokens / wall-clock deltas    : true aggregate throughput
    vLLM histograms (_sum/_count deltas)  : the server's own TTFT/queue/prefill/ITL means
    """
    ms = [s for s in samples if "metrics" in s]
    row: dict = {}
    if len(ms) >= 2:
        row |= {
            "m_scrapes": len(ms),
            # whole sampled span, not a mean of per-window ratios (counters only move when a request finishes)
            "m_counter_wall_tok_s": round((_get(ms[-1]["metrics"], GENERATED) - _get(ms[0]["metrics"], GENERATED))
                                          / (ms[-1]["t_mono"] - ms[0]["t_mono"]), 2) if ms[-1]["t_mono"] > ms[0]["t_mono"] else None,
            "m_deferred_max": max(_get(s["metrics"], QUEUED) for s in ms),
            "m_processing_max": max(_get(s["metrics"], RUNNING) for s in ms),
        }
    if ms and "kv_cache_usage_perc" in ms[-1]["metrics"]:
        row["m_kv_cache_usage_max"] = round(max(s["metrics"].get("kv_cache_usage_perc", 0) for s in ms), 4)
    base = (baseline or {}).get("metrics") or (ms[0]["metrics"] if ms else None)
    if base is not None and ms:
        last = ms[-1]["metrics"]
        for hist, key in VLLM_HISTOGRAMS.items():
            n = last.get(f"{hist}_count", 0) - base.get(f"{hist}_count", 0)
            if n > 0:
                row[key] = round((last.get(f"{hist}_sum", 0) - base.get(f"{hist}_sum", 0)) / n * 1e3, 3)
    if len(ms) >= 2 and "predicted_tokens_seconds" in ms[-1]["metrics"]:   # llama.cpp only
        gauges, per_slot, wall_rate, zero_windows = [], [], [], 0
        for a, b in zip(ms, ms[1:]):
            dt = b["t_mono"] - a["t_mono"]
            dn = b["metrics"].get("tokens_predicted_total", 0) - a["metrics"].get("tokens_predicted_total", 0)
            dsec = b["metrics"].get("tokens_predicted_seconds_total", 0) - a["metrics"].get("tokens_predicted_seconds_total", 0)
            g = b["metrics"].get("predicted_tokens_seconds", 0)
            gauges.append(g)
            zero_windows += g == 0
            if dsec > 0:
                per_slot.append(dn / dsec)
            if dt > 0:
                wall_rate.append(dn / dt)
        nonzero = [g for g in gauges if g > 0]
        row |= {
            "m_gauge_pred_tok_s_mean_nonzero": round(statistics.fmean(nonzero), 2) if nonzero else 0,
            "m_gauge_zero_windows": zero_windows,
            "m_counter_per_slot_tok_s": round(statistics.fmean(per_slot), 2) if per_slot else None,
            "m_busy_slots_per_decode_max": round(max(s["metrics"].get("n_busy_slots_per_decode", 0) for s in ms), 3),
        }
    if len(idle) == 2 and all("metrics" in s for s in idle) and "predicted_tokens_seconds" in idle[1]["metrics"]:
        row["m_idle_gauge_1st"] = idle[0]["metrics"].get("predicted_tokens_seconds")
        row["m_idle_gauge_2nd"] = idle[1]["metrics"].get("predicted_tokens_seconds")
    return row


SPREAD_KEYS = ("agg_output_tok_s", "steady_output_tok_s", "tpot_ms_p50", "ttft_ms_p95", "goodput_tok_s")


def combine_repeats(reps: list[dict]) -> dict:
    """Median of every numeric field across repeats, plus spread for the headline metrics.

    <key>_spread_pct = (max - min) / median x 100: how much the repeats disagree.
    """
    ok = [r for r in reps if r.get("status") == "ok"]
    if not ok:
        return reps[-1] if reps else {}
    out: dict = {"status": "ok", "repeats": len(ok)}
    if len(ok) < len(reps):
        out["repeats_failed"] = len(reps) - len(ok)
    for key in ok[0]:
        values = [r.get(key) for r in ok]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            med = statistics.median(values)
            out[key] = round(med, 3) if isinstance(med, float) else med
            if key in SPREAD_KEYS and len(values) > 1 and med:
                out[f"{key}_spread_pct"] = round((max(values) - min(values)) / med * 100, 1)
        elif key not in out:
            out[key] = values[-1]
    return out
