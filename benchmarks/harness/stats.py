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


def summarize_load(result: dict) -> dict:
    recs = result["records"]
    ok = [r for r in recs if r.get("ok")]
    out_tokens = sum(r["n_tokens"] for r in ok)
    timings = [r.get("timings", {}) for r in ok]
    row = {
        "requests_ok": len(ok),
        "requests_failed": len(recs) - len(ok),
        "wall_s": round(result["wall_s"], 3),
        "agg_output_tok_s": round(out_tokens / result["wall_s"], 2) if result["wall_s"] else None,
        "prompt_n_mean": round(statistics.fmean(t.get("prompt_n", 0) for t in timings), 1) if timings else None,
        "cache_n_mean": round(statistics.fmean(t.get("cache_n", 0) for t in timings), 1) if timings else None,
    }
    row |= dist("ttft_ms", [r["ttft_ms"] for r in ok])
    row |= dist("e2e_ms", [r["e2e_ms"] for r in ok])
    row |= dist("itl_ms", [x for r in ok for x in r["itl_ms"]])
    row |= dist("srv_prompt_ms", [t["prompt_ms"] for t in timings if "prompt_ms" in t])
    # Client TTFT minus server prefill time = HTTP + queueing + first decode step.
    row |= dist("ttft_minus_srv_prompt_ms", [
        r["ttft_ms"] - r["timings"]["prompt_ms"] for r in ok if "prompt_ms" in r.get("timings", {})
    ])
    row["srv_decode_tok_s_mean"] = round(statistics.fmean(
        t["predicted_per_second"] for t in timings if t.get("predicted_per_second")), 2) if timings else None
    row |= summarize_metrics(result["samples"], result["idle_probe"])
    return row


def summarize_metrics(samples: list[dict], idle: list[dict]) -> dict:
    """Compare the /metrics gauges against rates derived from counter deltas.

    gauge predicted_tokens_seconds        : what llama.cpp reports
    counter tokens/tokens_seconds deltas  : per-slot decode speed (time summed across slots)
    counter tokens / wall-clock deltas    : true aggregate throughput
    """
    ms = [s for s in samples if "metrics" in s]
    row: dict = {}
    if len(ms) >= 2:
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
            "m_scrapes": len(ms),
            "m_gauge_pred_tok_s_mean_nonzero": round(statistics.fmean(nonzero), 2) if nonzero else 0,
            "m_gauge_zero_windows": zero_windows,
            "m_counter_per_slot_tok_s": round(statistics.fmean(per_slot), 2) if per_slot else None,
            "m_counter_wall_tok_s": round(statistics.fmean(wall_rate), 2) if wall_rate else None,
            "m_deferred_max": max(s["metrics"].get("requests_deferred", 0) for s in ms),
            "m_processing_max": max(s["metrics"].get("requests_processing", 0) for s in ms),
            "m_busy_slots_per_decode_max": round(max(s["metrics"].get("n_busy_slots_per_decode", 0) for s in ms), 3),
        }
    if len(idle) == 2 and all("metrics" in s for s in idle):
        row["m_idle_gauge_1st"] = idle[0]["metrics"].get("predicted_tokens_seconds")
        row["m_idle_gauge_2nd"] = idle[1]["metrics"].get("predicted_tokens_seconds")
    return row
