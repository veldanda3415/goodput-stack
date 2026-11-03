"""H100 build: tables (markdown) from the raw rows under benchmarks/results/h100/raw/. Nothing here is measured.

    .venv/bin/python benchmarks/modal/report_h100.py h1        # H1 tables
    .venv/bin/python benchmarks/modal/report_h100.py h2 ...    # one section per argument

Every number printed is either copied from a JSONL row or CALCULATED from row values / config.json (labelled).
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "benchmarks" / "results" / "h100" / "raw"
DATASHEET = {"bf16_tflops": 989.0, "fp8_tflops": 1979.0, "hbm_gb_s": 3350.0, "max_sm_mhz_measured": 1980}
SHAPES = ["qkv", "o", "gate_up", "down"]


def rows(task: str) -> list[dict]:
    out = []
    for f in sorted(RAW.glob(f"*_{task}/{task}/{task}.jsonl")):
        for l in f.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                r["_src"] = str(f.relative_to(RAW.parent))
                out.append(r)
    return out


def micro_rows() -> list[dict]:
    f = next(iter(sorted(RAW.glob("*_h1/h1/micro/microbench.jsonl"))))
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def layers(model: str) -> int:
    return {"llama3.1-8b": 32, "qwen2.5-3b": 36}[model]


def h1() -> None:
    rs = micro_rows()
    print("| measurement | value |\n|---|---:|")
    for r in rs:
        if r["kind"] == "bandwidth":
            print(f"| {r['op']}, {r['tensor_bytes'] / 2**30:.0f} GiB fp32, median of {r['repeats']} (GB/s) | **{r['gb_s_median']:,.1f}** "
                  f"(min {r['gb_s_min']:,.1f}, max {r['gb_s_max']:,.1f}) |")
    print()
    print("| 8192³ GEMM, 60 s | first 0.1 s chunk | first 1 s | median after 10 s | SM MHz after 10 s (mean / min) | power W after 10 s (mean / max) | temp max °C | throttle reasons after 10 s | TFLOP/s per GHz (CALCULATED) |")
    print("|---|---:|---:|---:|---:|---:|---:|---|---:|")
    for r in rs:
        if r["kind"] != "gemm_sustained":
            continue
        reasons = ", ".join(f"{k.split('reason_')[1].removesuffix('_frac')} {100 * v:.0f} %" for k, v in r.items()
                            if k.startswith("after10s_gpu_reason") and k.endswith("_frac") and v) or "none"
        clk = r["after10s_gpu_clocks_sm_mean"]
        print(f"| {r['dtype']} ({r['op'].split('(')[0]}{', fast accum' if r['dtype'] == 'fp8fast' else ''}) | {r['tflops_first_chunk']:,.1f} | {r['tflops_first_1s']:,.1f} | "
              f"**{r['tflops_median_after_10s']:,.1f}** | {clk:,.0f} / {r['after10s_gpu_clocks_sm_min']:,.0f} | "
              f"{r['after10s_gpu_power_draw_mean']:.1f} / {r['after10s_gpu_power_draw_max']:.1f} | {r['after10s_gpu_temperature_gpu_max']:.0f} | "
              f"{reasons} | {r['tflops_median_after_10s'] / clk * 1000:,.1f} |")
    sh = [r for r in rs if r["kind"] == "shape"]
    ms = sorted({r["m"] for r in sh})
    for model in ("llama3.1-8b", "qwen2.5-3b"):
        for dt in ("bfloat16", "fp8"):
            sel = [r for r in sh if r["model"] == model and r["dtype"] == dt]
            print(f"\n{model}, {dt} (TFLOP/s; `torch.matmul(x[M,K], W[N,K].t())`" + (" / `torch._scaled_mm` e4m3, out bf16" if dt == "fp8" else "") + ")\n")
            print("| shape (K → N) | " + " | ".join(f"M={m}" for m in ms) + " |")
            print("|---|" + "---:|" * len(ms))
            for s in SHAPES + ["lm_head"]:
                rr = {r["m"]: r for r in sel if r["shape"] == s}
                k, n = next(iter(rr.values()))["k"], next(iter(rr.values()))["n"]
                print(f"| {s} ({k:,} → {n:,}) | " + " | ".join(f"{rr[m]['tflops']:,.1f}" for m in ms) + " |")
            # FLOP-weighted step mix: layers x [qkv, o, gate_up, down] + lm_head (CALCULATED from the per-shape times)
            mix, gb, clk = [], [], []
            for m in ms:
                rr = {r["shape"]: r for r in sel if r["m"] == m}
                fl = layers(model) * sum(rr[s]["flop_per_call"] for s in SHAPES) + rr["lm_head"]["flop_per_call"]
                t = layers(model) * sum(rr[s]["per_call_us_median"] for s in SHAPES) + rr["lm_head"]["per_call_us_median"]
                by = layers(model) * sum(rr[s]["min_bytes_per_call"] for s in SHAPES) + rr["lm_head"]["min_bytes_per_call"]
                mix.append(fl / t / 1e6)
                gb.append(by / t / 1e3)
                clk.append(statistics.fmean(r["gpu_clocks_sm_mean"] for r in rr.values() if r.get("gpu_clocks_sm_mean")))
            print("| **step mix (CALCULATED)** | " + " | ".join(f"**{x:,.1f}**" for x in mix) + " |")
            print("| step mix GB/s, minimum bytes (CALCULATED) | " + " | ".join(f"{x:,.0f}" for x in gb) + " |")
            print("| SM clock, mean over the 5 shapes (MHz) | " + " | ".join(f"{x:,.0f}" for x in clk) + " |")
    bw = next(r["gb_s_median"] for r in rs if r["kind"] == "bandwidth" and r["op"] == "copy")
    g = {r["dtype"]: r["tflops_median_after_10s"] for r in rs if r["kind"] == "gemm_sustained"}
    print(f"\nRidge (CALCULATED): achievable BF16 {g['bfloat16']:.1f} TFLOP/s ÷ {bw:,.1f} GB/s = **{g['bfloat16'] * 1e3 / bw:.0f} FLOP/byte**; "
          f"FP8 {g['fp8']:.1f} ÷ {bw:,.1f} = **{g['fp8'] * 1e3 / bw:.0f}**; DATASHEET BF16 {DATASHEET['bf16_tflops']:.0f} ÷ 3,350 = "
          f"{DATASHEET['bf16_tflops'] * 1e3 / DATASHEET['hbm_gb_s']:.0f}, FP8 {DATASHEET['fp8_tflops']:,.0f} ÷ 3,350 = {DATASHEET['fp8_tflops'] * 1e3 / DATASHEET['hbm_gb_s']:.0f}.")


if __name__ == "__main__":
    for sec in sys.argv[1:]:
        globals()[sec]()
