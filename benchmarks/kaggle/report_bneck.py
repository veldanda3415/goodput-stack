"""Tables, the G5 waterfall and the charts for Part G (stage bneck) from the session run directories.

    python -m benchmarks.kaggle.report_bneck benchmarks/results/t4/<P1>_bneck benchmarks/results/t4/<P2>_bneck [...]

Prints markdown tables (pasted into bottlenecks.md) and writes
    charts/bottlenecks_waterfall.png        datasheet ceiling -> measured, one bar per measured factor
    charts/bottlenecks_curve.png            measured offline curves vs the datasheet and the achievable ceilings
    <first run>/results/bneck/g5.json       every factor with its value and source

Model arithmetic (CALCULATED, Qwen2.5-3B-Instruct config.json @ aa8e7253):
    linear params per token   P_lin = 36 x (2048*2560 + 2048*2048 + 2048*22016 + 11008*2048) = 2,774,532,096
    lm_head params            P_lm  = 2048 x 151936 = 311,164,928 (tied embeddings: the same matrix)
    attention FLOP per token at context c = 36 layers x 4 x 16 heads x 128 x c = 294,912 c (QK^T and PV)
    weight bytes (fp16)       2 x (P_lin + P_lm) + norms; the log's 5.79 GiB is used where bytes are needed
    KV bytes per token        36 layers x 2 (K, V) x 2 KV heads x 128 x 2 B = 36,864 B
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

T4 = Path(__file__).resolve().parents[1] / "results" / "t4"
CHARTS = T4 / "charts"
P_LIN = 36 * (2048 * 2560 + 2048 * 2048 + 2048 * 22016 + 11008 * 2048)
P_LM = 2048 * 151936
ATTN_PER_CTX = 36 * 4 * 16 * 128
KV_BYTES_PER_TOKEN = 36 * 2 * 2 * 128 * 2
WEIGHT_BYTES = 5.79 * 2**30          # vLLM log "Model loading took 5.79 GiB" (Build 14)
PEAK_TFLOPS, PEAK_MHZ, PEAK_GBS = 65.0, 1590, 300.0   # T4 datasheet
SHAPE_K_N = {"qkv": (2048, 2560), "o": (2048, 2048), "gate_up": (2048, 22016), "down": (11008, 2048), "lm_head": (2048, 151936)}


def flop_per_output_token(in_len: int, out_len: int) -> float:
    """All FLOPs of one request (prompt + output tokens through the linear layers, one lm_head row per output token,
    attention over the growing context) divided by its output tokens. CALCULATED."""
    n = in_len + out_len
    attn = ATTN_PER_CTX * sum(range(1, n + 1))
    return (2 * P_LIN * n + 2 * P_LM * out_len + attn) / out_len


def decode_flop_per_token(ctx: float) -> float:
    return 2 * P_LIN + 2 * P_LM + ATTN_PER_CTX * ctx


def rows(run: Path) -> dict[str, dict]:
    out = {}
    p = run / "results" / "bneck" / "bneck.jsonl"
    for l in p.read_text().splitlines():
        if l.strip():
            r = json.loads(l)
            r["_run"] = run.name
            out[r["key"]] = r
    return out


def f(v, nd=0) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.{nd}f}"
    return str(v)


def reason_str(r: dict, prefix: str = "smi_") -> str:
    parts = []
    for k in ("sw_power_cap", "hw_slowdown", "hw_thermal_slowdown", "hw_power_brake_slowdown", "sw_thermal_slowdown", "gpu_idle",
              "applications_clocks_setting", "sync_boost"):
        v = r.get(f"{prefix}reason_{k}_frac")
        if v:
            parts.append(f"{k} {100 * v:.0f} %")
    return ", ".join(parts) or "none active"


def offline_line(r: dict) -> str:
    return (f"| {r['_run']} | `{r['key']}` | {f(r.get('output_tok_s'), 1)} | {f(r.get('total_tok_s'), 1)} | "
            f"{f(r.get('gpu_sm_clock_mhz_mean'))} ({f(r.get('smi_clocks_sm_mean'))}) | {f(r.get('smi_power_draw_mean'), 1)} / {f(r.get('smi_power_limit_mean'), 0)} | "
            f"{f(r.get('smi_temperature_gpu_max'))} | {reason_str(r)} | {f(r.get('gpu_util_gpu_pct_mean'), 1)} | {f(r.get('eng_preemptions_delta'))} | "
            f"{f(r.get('eng_running_mean'), 1)} | {f((r.get('bench_json') or {}).get('elapsed_time'), 1)} |")


OFF_HEAD = ("| run | key | output tok/s | total tok/s | SM clock mean MHz, NVML (nvidia-smi) | power draw / limit W | temp max °C | "
            "throttle reasons active (share of samples) | util.gpu % | preemptions | running mean | elapsed s |\n"
            "|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|")


def micro_tables(run: Path) -> dict:
    res = {}
    for d in sorted((run / "results" / "bneck").glob("micro-gpu*")):
        p = d / "microbench.jsonl"
        if not p.exists():
            continue
        ms = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        gpu = d.name.split("gpu")[-1]
        res[gpu] = ms
        print(f"\n#### G1 GPU {gpu} ({run.name}; {ms[0].get('device_name')}, {ms[0].get('smi_uuid')}, torch {ms[0].get('torch')}, "
              f"CUDA {ms[0].get('torch_cuda')}, driver {ms[0].get('smi_driver')})")
        for m in ms:
            if m["kind"] == "bandwidth":
                near = nearest_sample(d / "gpu.csv", *m["window_unix"])
                print(f"- {m['op']}: median **{m['gb_s_median']} GB/s** (min {m['gb_s_min']}, max {m['gb_s_max']}, {m['repeats']} repeats, "
                      f"{m['bytes_moved_per_op'] / 1e9:.2f} GB per op, {m['window_unix'][1] - m['window_unix'][0]:.2f} s); "
                      f"nearest sampler row ({near.get('dt_s')} s from the window): SM {near.get('clocks.sm')} MHz, "
                      f"mem clock {near.get('clocks.mem')} MHz, power {near.get('power.draw')} W, util.mem {near.get('util_mem_pct')} %")
            if m["kind"] == "gemm_sustained":
                print(f"- 8192³ FP16 GEMM, {m['seconds']:.0f} s: first chunk **{m['tflops_first_chunk']} TFLOP/s**, first second "
                      f"{m['tflops_first_1s']}, max chunk {m['tflops_max_chunk']}, median after 10 s **{m['tflops_median_after_10s']}**; "
                      f"after 10 s: SM {f(m.get('after10s_gpu_clocks_sm_mean'))} MHz (NVML {f(m.get('after10s_gpu_sm_clock_mhz_mean'))}), "
                      f"power {f(m.get('after10s_gpu_power_draw_mean'), 1)} W, limit {f(m.get('after10s_gpu_power_limit_mean'))} W, "
                      f"temp max {f(m.get('after10s_gpu_temperature_gpu_max'))} °C, reasons: {reason_str(m, 'after10s_gpu_')}")
                print("\n  | second | TFLOP/s | SM MHz (nvidia-smi) | NVML SM MHz | power W | sw_power_cap |\n  |---:|---:|---:|---:|---:|---:|")
                for s in m["per_second"]:
                    if s["second"] < 5 or s["second"] % 10 == 0:
                        print(f"  | {s['second']} | {s['tflops_mean']} | {f(s.get('gpu_clocks_sm_mean'))} | {f(s.get('gpu_sm_clock_mhz_mean'))} | "
                              f"{f(s.get('gpu_power_draw_mean'), 1)} | {f(100 * s['gpu_reason_sw_power_cap_frac'] if s.get('gpu_reason_sw_power_cap_frac') is not None else None)} % |")
        shapes = [m for m in ms if m["kind"] == "shape"]
        if shapes:
            mlist = sorted({m["m"] for m in shapes})
            print("\n  TFLOP/s by shape and M (CALCULATED from 2MNK / median call time); GB/s CALCULATED from minimum bytes:\n")
            print("  | shape (K → N) | " + " | ".join(f"M={x}" for x in mlist) + " |\n  |---|" + "---:|" * len(mlist))
            for name in SHAPE_K_N:
                cells = []
                for x in mlist:
                    m = next((s for s in shapes if s["shape"] == name and s["m"] == x), None)
                    cells.append(f"{m['tflops']:.1f} ({m['gb_s_calculated']:.0f} GB/s)" if m else "—")
                print(f"  | {name} ({SHAPE_K_N[name][0]} → {SHAPE_K_N[name][1]}) | " + " | ".join(cells) + " |")
            print("\n  | M | " + " | ".join(f"M={x}" for x in mlist) + " |\n  |---|" + "---:|" * len(mlist))
            clk = []
            for x in mlist:
                v = [s.get("gpu_clocks_sm_mean") for s in shapes if s["m"] == x and s.get("gpu_clocks_sm_mean")]
                clk.append(f"{statistics.fmean(v):.0f}" if v else "—")
            print("  | SM clock mean over the 5 shapes, MHz | " + " | ".join(clk) + " |")
    return res


def nearest_sample(path: Path, t0: float, t1: float) -> dict:
    """The sampler row closest to [t0, t1] (inside it if any); for runs shorter than one sampling interval."""
    import csv
    with open(path) as fh:
        rs = [r for r in csv.DictReader(fh) if not r.get("error") and r.get("clocks.sm")]
    if not rs:
        return {}
    dist = lambda r: max(0.0, t0 - float(r["t_unix"]), float(r["t_unix"]) - t1)
    best = min(rs, key=dist)
    return best | {"dt_s": round(dist(best), 2)}


def shape_mix_rate(ms: list[dict], m: int, include_lm: bool = True) -> tuple[float, float] | None:
    """FLOP-weighted TFLOP/s of one decode step's GEMMs at M (36 x [qkv, o, gate_up, down] + lm_head), and the mean
    SM clock over those points. CALCULATED from the per-shape microbench rates."""
    sel = {s["shape"]: s for s in ms if s["kind"] == "shape" and s["m"] == m}
    if not all(k in sel for k in SHAPE_K_N):
        return None
    t = fl = 0.0
    for name, (k, n) in SHAPE_K_N.items():
        if name == "lm_head" and not include_lm:
            continue
        cnt = 1 if name == "lm_head" else 36
        flop = cnt * 2 * m * k * n
        fl += flop
        t += flop / (sel[name]["tflops"] * 1e12)
    clk = [sel[n].get("gpu_clocks_sm_mean") for n in SHAPE_K_N if sel[n].get("gpu_clocks_sm_mean")]
    return fl / t / 1e12, (statistics.fmean(clk) if clk else None)


def breakdown(run: Path, key: str) -> dict | None:
    p = run / "results" / "bneck" / f"{key}.breakdown.json"
    return json.loads(p.read_text()) if p.exists() else None


BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"   # dataviz default categorical slots 1-4
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def g5(p1: Path, p2: Path, b14: Path) -> dict:
    """The waterfall and the recomputed ceilings. Every input is a measured row (source recorded) or model arithmetic."""
    from benchmarks.kaggle import trace_breakdown as tb
    r1, r2 = rows(p1), rows(p2)
    b14r = {json.loads(l)["key"]: json.loads(l) for l in (b14 / "results/ridge/ridge.jsonl").read_text().splitlines() if l.strip()}
    trace = next((p1 / "results/bneck/trace-mns384").glob("*.pt.trace.json.gz"))
    an = tb.analyze(tb.load(trace))
    dec = [s for s in an["per_step"] if s["ctx_reqs"] == 0]
    allst = an["per_step"]
    dec_period = sum(s["gpu_period_us"] for s in dec)
    gemm = sum(s["gemm_us"] for s in dec)
    attn = sum(s["attn_us"] for s in dec)
    busy = sum(s["busy_us"] for s in dec)
    flops = sum(s["linear_flops"] for s in dec)
    r_gemm = flops / gemm / 1e6                                     # TFLOP/s inside the GEMM kernels, decode steps
    prof_clk = r1["prof-mns384"]["smi_clocks_sm_mean"]
    dec_rate = sum(s["gen_tokens"] for s in dec) / (dec_period / 1e6)
    all_rate = sum(s["gen_tokens"] for s in allst) / (sum(s["gpu_period_us"] for s in allst) / 1e6)
    f_dec = 2 * P_LIN + 2 * P_LM
    ctx = statistics.fmean(s["kv_tokens"] / s["gen_reqs"] for s in dec)
    eta = (r_gemm / prof_clk) / (PEAK_TFLOPS / PEAK_MHZ)            # GEMM efficiency per clock, clock-independent assumed
    other = busy - gemm - attn
    factors = {
        "clock": None,
        "gemm_efficiency": eta,
        "attention": (gemm + other) / busy,
        "other_kernels": gemm / (gemm + other),
        "idle": busy / dec_period,
        "prompt_share": all_rate / dec_rate,
    }
    targets = {"Build 14 offline-mns384 (20261031-082141_ridge)": (b14r["offline-mns384"]["output_tok_s"], b14r["offline-mns384"]["gpu_sm_clock_mhz_mean"]),
               f"P1 ref-start ({p1.name})": (r1["ref-start"]["output_tok_s"], r1["ref-start"]["smi_clocks_sm_mean"]),
               f"P1 ref-end ({p1.name})": (r1["ref-end"]["output_tok_s"], r1["ref-end"]["smi_clocks_sm_mean"]),
               f"P1 ref-gpu1 ({p1.name})": (r1["ref-gpu1"]["output_tok_s"], r1["ref-gpu1"]["smi_clocks_sm_mean"]),
               f"P2 ref-start ({p2.name})": (r2["ref-start"]["output_tok_s"], r2["ref-start"]["smi_clocks_sm_mean"]),
               f"P2 ref-end ({p2.name})": (r2["ref-end"]["output_tok_s"], r2["ref-end"]["smi_clocks_sm_mean"])}
    d0 = PEAK_TFLOPS * 1e12 / f_dec
    out = {"inputs": {"datasheet_tflops": PEAK_TFLOPS, "datasheet_mhz": PEAK_MHZ, "flop_per_decode_token_linear_and_lm_head": f_dec,
                      "flop_per_output_token_mixed_128_256": flop_per_output_token(128, 256),
                      "datasheet_mixed_ceiling_tok_s": PEAK_TFLOPS * 1e12 / flop_per_output_token(128, 256),
                      "trace": str(trace.resolve().relative_to(T4)), "profile_clock_mhz": prof_clk, "decode_steps": len(dec), "all_steps": len(allst),
                      "gemm_tflops_in_vllm_decode": r_gemm, "decode_rate_in_trace": dec_rate, "all_steps_rate_in_trace": all_rate,
                      "mean_context_decode": ctx, "gemm_us": gemm, "attention_us": attn, "other_us": other, "busy_us": busy,
                      "period_us": dec_period},
           "factors": factors, "datasheet_decode_ceiling": d0, "chains": {}}
    for name, (meas, clk) in targets.items():
        chain = [("datasheet decode ceiling (65 TFLOP/s ÷ 6.17 GFLOP per decode token)", d0)]
        v = d0 * clk / PEAK_MHZ
        chain.append((f"× SM clock {clk:.0f} / 1,590 MHz", v))
        for k, lab in (("gemm_efficiency", "× GEMM efficiency per clock"), ("attention", "− attention kernel time"),
                       ("other_kernels", "− norm / activation / sampling / memcpy time"), ("idle", "− GPU idle between kernels"),
                       ("prompt_share", "− prompt (prefill) steps")):
            v *= factors[k]
            chain.append((lab, v))
        out["chains"][name] = {"steps": chain, "predicted": v, "measured": meas, "clock_mhz": clk,
                               "residual_pct": 100 * (meas / v - 1)}
    return out


def waterfall_chart(g: dict, key: str, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ch = g["chains"][key]
    labels = [s[0] for s in ch["steps"]] + ["measured (vllm bench throughput)"]
    vals = [s[1] for s in ch["steps"]] + [ch["measured"]]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    y = list(range(len(vals)))[::-1]
    colors = [BLUE] * (len(vals) - 1) + [ORANGE]
    ax.barh(y, vals, color=colors, height=0.62, edgecolor="#fcfcfb", linewidth=2)
    for yi, v, lab in zip(y, vals, labels):
        ax.text(v + 120, yi, f"{v:,.0f}", va="center", fontsize=9, color=INK)
    ax.set_yticks(y, labels, fontsize=9, color=INK)
    ax.set_xlabel("output tokens / s (CALCULATED except the last bar)", color=INK2)
    fig.suptitle(f"From the datasheet ceiling to the measured {ch['measured']:,.0f} tok/s — Qwen2.5-3B FP16, one T4, max-num-seqs 384\n"
                 f"{key}; residual (unexplained) {ch['residual_pct']:+.1f} % — Kaggle T4, real", fontsize=9.5, color=INK, x=0.02, ha="left")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(colors=INK2, length=0)
    ax.set_xlim(0, max(vals) * 1.12)
    fig.subplots_adjust(top=0.86)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label="after each measured factor (CALCULATED)"), Patch(color=ORANGE, label="measured")],
              fontsize=8, frameon=False, loc="lower right")
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())


def curve_chart(b14: Path, p2: Path, g: dict, micro_tf: float, copy_gbs: float, path: Path) -> None:
    """Measured offline curves and the decode roofline with datasheet and achievable (G1) peaks, against max-num-seqs."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b14r = [json.loads(l) for l in (b14 / "results/ridge/ridge.jsonl").read_text().splitlines() if l.strip()]
    mixed = sorted((r["max_num_seqs"], r["output_tok_s"]) for r in b14r if r.get("kind") == "offline" and r.get("output_tok_s"))
    r2 = rows(p2)
    dec = sorted((r["max_num_seqs"], r["output_tok_s"]) for k, r in r2.items() if k.startswith("dec-mns") and "-out" not in k and r.get("output_tok_s"))
    d256 = r2.get("dec-mns384-out256")
    f_dec = 2 * P_LIN + 2 * P_LM
    ctx = g["inputs"]["mean_context_decode"]
    xs = list(range(8, 529, 8))

    def roof(tf, gbs):   # decode step: B x f_dec FLOP, weights + B x ctx KV bytes
        return [min(tf * 1e12 / f_dec, b * gbs * 1e9 / (WEIGHT_BYTES + b * ctx * KV_BYTES_PER_TOKEN)) for b in xs]
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.plot(xs, roof(PEAK_TFLOPS, PEAK_GBS), color=INK2, lw=1.5, ls="--")
    ax.text(530, roof(PEAK_TFLOPS, PEAK_GBS)[-1], " datasheet roofline, decode\n (65 TFLOP/s, 300 GB/s)", fontsize=8, color=INK2, va="center")
    ax.plot(xs, roof(micro_tf, copy_gbs), color=INK2, lw=1.5, ls=":")
    ax.text(530, roof(micro_tf, copy_gbs)[-1], f" achievable roofline, decode\n (G1: {micro_tf:.1f} TFLOP/s, {copy_gbs:.0f} GB/s)", fontsize=8, color=INK2, va="center")
    dm = g["inputs"]["datasheet_mixed_ceiling_tok_s"]
    am = micro_tf * 1e12 / g["inputs"]["flop_per_output_token_mixed_128_256"]
    ax.axhline(dm, color=ORANGE, lw=1, ls="--")
    ax.text(10, dm, f" datasheet ceiling, 128 in / 256 out: {dm:,.0f} (CALCULATED)", fontsize=8, color=INK2, va="bottom")
    ax.axhline(am, color=ORANGE, lw=1, ls=":")
    ax.text(10, am, f" achievable ceiling, 128 in / 256 out: {am:,.0f} (CALCULATED)", fontsize=8, color=INK2, va="bottom")
    ax.plot([x for x, _ in dec], [y for _, y in dec], "o-", color=BLUE, lw=2, ms=8, label="measured decode-only, 16 in / 512 out (G3.1)")
    ax.plot([x for x, _ in mixed], [y for _, y in mixed], "s-", color=ORANGE, lw=2, ms=8, label="measured 128 in / 256 out (Build 14)")
    if d256:
        ax.plot([384], [d256["output_tok_s"]], "D", color=AQUA, ms=9, label="measured decode-only, 16 in / 256 out (G3.1)")
    for pts, dy in ((dec, 9), (mixed, -15)):
        for x, y in pts:
            ax.annotate(f"{y:,.0f}", (x, y), textcoords="offset points", xytext=(0, dy), ha="center", fontsize=7.5, color=INK)
    if d256:
        ax.annotate(f"{d256['output_tok_s']:,.0f}", (384, d256["output_tok_s"]), textcoords="offset points", xytext=(10, 0),
                    va="center", fontsize=7.5, color=INK)
    ax.set_xlabel("max requests per step (--max-num-seqs)", color=INK2)
    ax.set_ylabel("output tokens / s", color=INK2)
    ax.set_title("Qwen2.5-3B FP16 on one T4: measured offline throughput vs ceilings — Kaggle T4, real", fontsize=10, color=INK, loc="left")
    ax.set_yscale("log")
    ax.set_ylim(300, 20000)
    ax.set_xlim(0, 700)
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors=INK2)
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=fig.get_facecolor())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", type=Path, nargs="+")
    ap.add_argument("--build14", type=Path, default=T4 / "20261031-082141_ridge")
    a = ap.parse_args()
    R = {run.name: rows(run) for run in a.runs}
    allr = [r for rs in R.values() for r in rs.values()]
    off = [r for r in allr if r.get("kind") == "offline"]
    print("### offline rows (all sessions)\n")
    print(OFF_HEAD)
    for r in off:
        print(offline_line(r))
    for r in allr:
        if r.get("kind") in ("error", "skipped") or (r.get("kind") == "offline" and r.get("rc") not in (0, None)):
            print(f"\n- {r['_run']} `{r['key']}` {r.get('kind')} rc={r.get('rc')}: {r.get('reason') or r.get('error') or ''} "
                  f"{(r.get('error_lines') or [''])[-3:]}")
    micro = {}
    for run in a.runs:
        micro |= {f"{run.name}/gpu{g}": ms for g, ms in micro_tables(run).items()}
    for run in a.runs:
        for mns in (64, 384):
            b = breakdown(run, f"prof-mns{mns}")
            if b:
                print(f"\n#### G2 profile max-num-seqs {mns} ({run.name})\n")
                print(json.dumps({k: b.get(k) for k in ("window_us", "steps_in_window", "share_pct_of_window", "overlap_us", "gap_us",
                                                        "unjoined_device_events", "steps")}, indent=1))
                print(json.dumps(b.get("per_shape"), indent=1)[:3000])
                print(json.dumps(b.get("subcategory_us"), indent=1)[:2000])
                for k in b.get("top_kernels", [])[:15]:
                    print(f"  {k['pct_of_device_time']:5.1f} %  {k['count']:6d}  {k['category']:28s} {k['name'][:110]}")
    if len(a.runs) >= 2:
        g = g5(a.runs[0], a.runs[1], a.build14)
        (a.runs[0] / "results/bneck/g5.json").write_text(json.dumps(g, indent=1) + "\n")
        print("\n### G5\n", json.dumps(g["inputs"], indent=1), json.dumps(g["factors"], indent=1))
        for name, ch in g["chains"].items():
            print(f"\n{name}: predicted {ch['predicted']:,.1f}, measured {ch['measured']:,.1f}, residual {ch['residual_pct']:+.2f} %")
            for lab, v in ch["steps"]:
                print(f"   {v:9,.1f}  {lab}")
        CHARTS.mkdir(parents=True, exist_ok=True)
        waterfall_chart(g, next(iter(g["chains"])), CHARTS / "bottlenecks_waterfall.png")
        m0 = [m for m in micro.get(f"{a.runs[0].name}/gpu0", []) if m["kind"] in ("gemm_sustained", "bandwidth")]
        tf = next(m["tflops_median_after_10s"] for m in m0 if m["kind"] == "gemm_sustained")
        bw = next(m["gb_s_median"] for m in m0 if m.get("op") == "copy")
        curve_chart(a.build14, a.runs[1], g, tf, bw, CHARTS / "bottlenecks_curve.png")
        print("charts ->", CHARTS / "bottlenecks_waterfall.png", CHARTS / "bottlenecks_curve.png")


if __name__ == "__main__":
    main()
