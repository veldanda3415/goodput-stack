"""Tables for Build 17 (stage mpsab): S / T / M, order S T M M T S, per run and per condition, tok/s per MHz.

    python -m benchmarks.kaggle.report_mpsab benchmarks/results/t4/<run-id>_mpsab [--json out.json]

Reads <run>/results/mpsab/mpsab.jsonl (rows cond-*, cond-*-state, startup-*) and the raw requests-i*.jsonl(.gz) of each
condition (pooled ITL / TTFT over both instances, same window as the row). Prints markdown tables.

CALCULATED here (not measured by a tool): tok/s per MHz = combined output tok/s / mean SM clock (nvidia-smi clocks.sm,
1 Hz, over the measured window); condition mean = mean of its runs; spread = (max - min) / mean of the runs, in %;
throttle-reason % = share of 1 Hz samples in the window with the reason Active.
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
from pathlib import Path

from benchmarks.kaggle.t4_notebook import window_stats

REASONS = ("sw_power_cap", "hw_slowdown", "hw_thermal_slowdown", "sw_thermal_slowdown", "hw_power_brake_slowdown",
           "gpu_idle", "applications_clocks_setting")


def load(run: Path) -> tuple[list[dict], dict]:
    d = run / "results" / "mpsab"
    rows = [json.loads(l) for l in (d / "mpsab.jsonl").read_text().splitlines() if l.strip()]
    return rows, {r["key"]: r for r in rows}


def run_row(d: Path, r: dict, by_key: dict) -> dict:
    tag = r["key"].removeprefix("cond-")
    inst = sorted(k.removeprefix("inst_") for k in r if k.startswith("inst_"))
    recs = []
    for n in inst:
        f = d / r["key"] / f"requests-{n}.jsonl"
        gz = f.with_name(f.name + ".gz")   # committed gzipped (token timestamps make them ~0.75 MB each)
        text = f.read_text() if f.exists() else gzip.decompress(gz.read_bytes()).decode() if gz.exists() else ""
        recs += [json.loads(l) for l in text.splitlines() if l.strip()]
    w0, w1 = r["window_unix"]
    pooled = window_stats(recs, w0, w1) if recs else {}
    clk = r.get("smi_clocks_sm_mean")
    state = by_key.get(f"{r['key']}-state", {})
    out = {
        "run": tag, "order": r["order_index"], "condition": r["condition"], "repeat": r["repeat"], "timestamp_utc": r["timestamp_utc"],
        "combined_tok_s": r["combined_output_tok_s"], "server_counter_tok_s": r.get("combined_output_tok_s_server_counters"),
        "per_instance_tok_s": {n: r[f"inst_{n}"]["output_tok_s"] for n in inst},
        "tok_s_per_mhz": round(r["combined_output_tok_s"] / clk, 4) if clk else None,
        "ttft_p50": pooled.get("ttft_ms_p50"), "ttft_p95": pooled.get("ttft_ms_p95"),
        "itl_p50": pooled.get("itl_ms_p50"), "itl_p95": pooled.get("itl_ms_p95"),
        "per_instance_itl_p50": {n: r[f"inst_{n}"].get("itl_ms_p50") for n in inst},
        "per_instance_ttft_p50": {n: r[f"inst_{n}"].get("ttft_ms_p50") for n in inst},
        "sm_clock_mean": clk, "sm_clock_min": r.get("smi_clocks_sm_min"), "sm_clock_max": r.get("smi_clocks_sm_max"),
        "nvml_sm_clock_mean": r.get("gpu_sm_clock_mhz_mean"),
        "power_mean": r.get("smi_power_draw_mean"), "power_limit": r.get("smi_power_limit_mean"),
        "enforced_power_limit": r.get("smi_enforced_power_limit_mean"),
        "temp_window_mean": r.get("smi_temperature_gpu_mean"), "temp_window_max": r.get("smi_temperature_gpu_max"),
        "temp_condition_start": (r.get("gpu_at_condition_start") or {}).get("temperature.gpu"),
        "temp_load_start": (r.get("gpu_at_load_start") or {}).get("temperature.gpu"),
        "idle_before_s": r.get("idle_before_s"),
        "throttle_pct": {k: round(100 * r[f"smi_reason_{k}_frac"], 1) for k in REASONS if r.get(f"smi_reason_{k}_frac") is not None},
        "gpu_samples": r.get("gpu_samples"), "util_gpu_mean": r.get("gpu_util_gpu_pct_mean"),
        "kv_usage_peak": {n: r[f"inst_{n}"].get("srv_kv_usage_max") for n in inst},
        "running_mean": {n: r[f"inst_{n}"].get("srv_running_mean") for n in inst},
        "preemptions": {n: r[f"inst_{n}"].get("srv_preemptions_delta") for n in inst},
        "errors": sum(r[f"inst_{n}"]["errors"] for n in inst),
        "requests_completed": sum(r[f"inst_{n}"]["requests_completed"] for n in inst),
        "cancelled_at_end": sum(r[f"inst_{n}"]["requests_cancelled_at_window_end"] for n in inst),
        "usage_completion_tokens": sorted({x for n in inst for x in r[f"inst_{n}"]["usage_completion_tokens_completed"]}, key=str),
        "window_s": r["window_s"], "kv_pool_tokens": r.get("kv_pool_tokens"), "startup_s": r.get("startup_s"),
        "mps_state_ok": r.get("mps_state_ok"), "engine_cores_as_mps_clients": state.get("engine_cores_as_mps_clients"),
        "mps_client_lines": state.get("mps_client_lines"), "mps_processes": state.get("mps_processes"),
        "cpu_sys_mean": r.get("cpu_sys_pct_mean"),
    }
    return out


def spread(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    m = statistics.fmean(vals)
    return round((max(vals) - min(vals)) / m * 100, 2) if m else None


def per_condition(runs: list[dict]) -> dict:
    out = {}
    for c in ("S", "T", "M"):
        rs = [r for r in runs if r["condition"] == c]
        if not rs:
            continue
        agg = {"n": len(rs), "runs": [r["run"] for r in rs]}
        for k in ("combined_tok_s", "tok_s_per_mhz", "itl_p50", "itl_p95", "ttft_p50", "ttft_p95", "sm_clock_mean", "power_mean",
                  "temp_window_mean"):
            vals = [r[k] for r in rs if r[k] is not None]
            agg[k] = round(statistics.fmean(vals), 4) if vals else None
            agg[f"{k}_values"] = vals
            agg[f"{k}_spread_pct"] = spread(vals)
        reasons = sorted({k for r in rs for k in r["throttle_pct"]})
        agg["throttle_pct"] = {k: round(statistics.fmean([r["throttle_pct"].get(k, 0) for r in rs]), 1) for k in reasons}
        out[c] = agg
    return out


def fmt(v, nd=1):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rows, by_key = load(a.run)
    d = a.run / "results" / "mpsab"
    conds = sorted((r for r in rows if r.get("kind") == "condition"), key=lambda r: r["order_index"])
    runs = [run_row(d, r, by_key) for r in conds]
    agg = per_condition(runs)

    print("| # | cond | rep | combined tok/s | per instance | server ctr tok/s | tok/s per MHz | TTFT p50 / p95 ms | ITL p50 / p95 ms "
          "| SM clock mean (min–max) MHz | power W (limit) | temp °C start / window | throttle reasons % | KV peak | errors | MPS check |")
    print("|" + "---|" * 15)
    for r in runs:
        th = ", ".join(f"{k} {v:g}" for k, v in r["throttle_pct"].items() if v) or "none"
        mps = f"{r['engine_cores_as_mps_clients']} M+C" + (" ok" if r["mps_state_ok"] else " FAIL")
        print(f"| {r['order']} | {r['condition']} | {r['repeat']} | **{fmt(r['combined_tok_s'])}** | "
              f"{' / '.join(fmt(v) for v in r['per_instance_tok_s'].values())} | {fmt(r['server_counter_tok_s'])} | "
              f"{fmt(r['tok_s_per_mhz'], 4)} | {fmt(r['ttft_p50'], 0)} / {fmt(r['ttft_p95'], 0)} | {fmt(r['itl_p50'])} / {fmt(r['itl_p95'])} | "
              f"{fmt(r['sm_clock_mean'], 0)} ({fmt(r['sm_clock_min'], 0)}–{fmt(r['sm_clock_max'], 0)}) | "
              f"{fmt(r['power_mean'])} ({fmt(r['power_limit'])}) | {r['temp_condition_start']} / {fmt(r['temp_window_mean'])} | {th} | "
              f"{' / '.join(fmt(v, 4) for v in r['kv_usage_peak'].values())} | {r['errors']} | {mps} |")
    print()
    print("| cond | runs | combined tok/s mean (spread %) | tok/s per MHz mean (spread %) | ITL p50 ms (spread %) | ITL p95 ms "
          "| TTFT p50 ms | SM clock MHz mean (spread %) | power W | throttle reasons % |")
    print("|" + "---|" * 10)
    for c, g in agg.items():
        th = ", ".join(f"{k} {v:g}" for k, v in g["throttle_pct"].items() if v) or "none"
        print(f"| {c} | {g['n']} | **{fmt(g['combined_tok_s'])}** ({fmt(g['combined_tok_s_spread_pct'], 2)}) | "
              f"**{fmt(g['tok_s_per_mhz'], 4)}** ({fmt(g['tok_s_per_mhz_spread_pct'], 2)}) | {fmt(g['itl_p50'], 2)} ({fmt(g['itl_p50_spread_pct'], 2)}) | "
              f"{fmt(g['itl_p95'], 2)} | {fmt(g['ttft_p50'], 0)} | {fmt(g['sm_clock_mean'], 0)} ({fmt(g['sm_clock_mean_spread_pct'], 2)}) | "
              f"{fmt(g['power_mean'])} | {th} |")
    if "M" in agg and "T" in agg and agg["M"]["tok_s_per_mhz"] and agg["T"]["tok_s_per_mhz"]:
        m, t = agg["M"]["tok_s_per_mhz"], agg["T"]["tok_s_per_mhz"]
        print(f"\nM vs T per MHz: {(m / t - 1) * 100:+.2f} % (CALCULATED); within-condition spreads: "
              f"M {agg['M']['tok_s_per_mhz_spread_pct']} %, T {agg['T']['tok_s_per_mhz_spread_pct']} %")
        print(f"M vs T raw tok/s: {(agg['M']['combined_tok_s'] / agg['T']['combined_tok_s'] - 1) * 100:+.2f} %")
    print("\norder (repeat 2 vs repeat 1):")
    for c in agg:
        rs = sorted((r for r in runs if r["condition"] == c), key=lambda r: r["repeat"])
        if len(rs) == 2:
            a1, a2 = rs
            print(f"  {c}: tok/s {a1['combined_tok_s']} -> {a2['combined_tok_s']} ({(a2['combined_tok_s'] / a1['combined_tok_s'] - 1) * 100:+.2f} %), "
                  f"per MHz {a1['tok_s_per_mhz']} -> {a2['tok_s_per_mhz']} ({(a2['tok_s_per_mhz'] / a1['tok_s_per_mhz'] - 1) * 100:+.2f} %), "
                  f"clock {a1['sm_clock_mean']} -> {a2['sm_clock_mean']}, temp start {a1['temp_condition_start']} -> {a2['temp_condition_start']}")
    if a.json:
        a.json.write_text(json.dumps({"runs": runs, "conditions": agg}, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
