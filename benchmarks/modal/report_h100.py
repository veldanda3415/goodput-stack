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


def reasons(r: dict, prefix: str = "smi_") -> str:
    out = [f"{k[len(prefix) + 7:-5]} {100 * v:.0f} %" for k, v in sorted(r.items())
           if k.startswith(prefix + "reason_") and k.endswith("_frac") and v and "gpu_idle" not in k]
    return ", ".join(out) or "none"


def offline_table(rs: list[dict], keys: list[str] | None = None, extra_col: str | None = None) -> None:
    """One markdown row per offline result (rows in `keys` order if given)."""
    by = {r["key"]: r for r in rs if r.get("kind") == "offline"}
    sel = [by[k] for k in keys if k in by] if keys else list(by.values())
    hdr = ["key", "max-num-seqs", "prompts", "output tok/s", "total tok/s", "timed s", "running mean", "KV use max",
           "preempt.", "SM MHz mean", "power W mean", "throttle (excl. idle)", "GPU util %", "EngineCore CPU % mean / max",
           "start+stop s"]
    if extra_col:
        hdr.insert(1, extra_col)
    print("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr))
    for r in sel:
        el = (r.get("bench_json") or {}).get("elapsed_time")
        cells = [f"`{r['key']}`", str(r["max_num_seqs"]), str(r["num_prompts"]),
                 f"**{r['output_tok_s']:,.1f}**" if r.get("output_tok_s") else f"rc {r.get('rc')}",
                 f"{r['total_tok_s']:,.1f}" if r.get("total_tok_s") else "",
                 f"{el:.1f}" if el else "", f"{r.get('eng_running_mean', 0):,.0f}",
                 f"{r.get('eng_kv_usage_max', 0):.3f}", f"{r.get('eng_preemptions_delta', '')}",
                 f"{r.get('smi_clocks_sm_mean', 0):,.0f}", f"{r.get('smi_power_draw_mean', 0):.0f}", reasons(r),
                 f"{r.get('gpu_util_gpu_pct_mean', 0):.0f}",
                 f"{r.get('cpu_engine_pct_mean', 0):.0f} / {r.get('cpu_engine_pct_max', 0):.0f}",
                 f"{r.get('start_and_teardown_s') or wall(r):.0f}" if (r.get('start_and_teardown_s') or wall(r)) else ""]
        if extra_col:
            cells.insert(1, str(r.get(extra_col.split()[0].lower().replace("-", "_"), "")))
        print("| " + " | ".join(cells) + " |")


_WALLS: dict = {}


def wall(r: dict):
    if not _WALLS:
        for task in ("h2", "h3", "h4", "h5"):
            for x in rows(task):
                if x.get("kind") == "wall":
                    _WALLS[(x["run_id"], x["of"])] = x.get("start_and_teardown_s")
    return _WALLS.get((r.get("run_id"), r["key"]))


def h2() -> None:
    rs = [r for r in rows("h2") if r.get("run_id") != "20261103-073941_h2"]   # the stopped first try (mbt 16,384)
    sweep = sorted((r for r in rs if r.get("kind") == "offline" and (r["key"].startswith("sweep-") or r["key"] == "ref-start")),
                   key=lambda r: r["max_num_seqs"])
    print("Sweep (in 128 / out 256, util 0.95, max-num-batched-tokens 8,192, num-prompts 4 x max-num-seqs; 384 = ref-start):\n")
    offline_table(rs, [r["key"] for r in sweep])
    print("\nAblations, profiles, end reference:\n")
    offline_table(rs, [r["key"] for r in rs if r.get("kind") == "offline" and r not in sweep])
    first = next(r for r in rs if r.get("kind") == "offline")
    print(f"\nGPU {first.get('gpu_uuid')}, Modal task {first.get('modal_task_id')}, region {first.get('modal_region')}, "
          f"{first.get('modal_cloud')}; KV cache {first.get('gpu_kv_cache_tokens'):,} tokens; backend lines: {first.get('attention_backend_lines')}")


def h3() -> None:
    rs = rows("h3")
    for tag in ("a-bf16", "b-fp8", "c-fp8kv"):
        sel = sorted((r for r in rs if r.get("kind") == "offline" and r.get("config") == tag and r.get("sweep")),
                     key=lambda r: r["max_num_seqs"])
        if not sel:
            continue
        print(f"\n{tag}: `{sel[0]['model']}` @ `{sel[0]['model_revision'][:8]}`, KV cache {sel[0].get('gpu_kv_cache_tokens') or 0:,} tokens, "
              f"weights {sel[0].get('model_weights_gib')} GiB, KV memory {sel[0].get('available_kv_gib')} GiB\n")
        offline_table(rs, [r["key"] for r in sel])
    prof = [r for r in rs if r.get("kind") == "offline" and r.get("profiler_config")]
    if prof:
        print("\nProfiled runs (speed not used):\n")
        offline_table(rs, [r["key"] for r in prof])


def h4() -> None:
    rs = rows("h4")
    offline_table(rs, [r["key"] for r in rs if r.get("kind") == "offline"])
    for r in rs:
        if r.get("kind") == "offline":
            print(f"- `{r['key']}`: prompt tokens {r.get('total_prompt_tokens')}, output {r.get('total_output_tokens')}, "
                  f"elapsed {(r.get('bench_json') or {}).get('elapsed_time')}, eng prompt tok/s {r.get('eng_prompt_tokens_per_s')}, "
                  f"rule {r.get('mns_rule', '')}")


def h5() -> None:
    rs = rows("h5")
    off = [r for r in rs if r.get("kind") == "offline"]
    if off:
        offline_table(rs, [r["key"] for r in off])
    http = sorted((r for r in rs if r.get("kind") == "http"), key=lambda r: (r["users"], r["client_processes"]))
    print("\n| users | client procs | requests ok / all | output tok/s (harness steady, sum) | engine gen tok/s (/metrics, full window) | "
          "TTFT p50 / p95 ms | ITL p50 / p95 ms | running mean | waiting mean / max | KV use max | SM MHz | power W | client CPU % mean / max | server CPU % mean |")
    print("|" + "---:|" * 15)
    for r in http:
        full = bool(r.get("srv_samples"))
        g = (lambda k: r.get(k, 0)) if full else (lambda k: r.get("run_" + k, 0))   # whole run when no full window
        na = lambda v, f: f.format(v) if full else "—"
        print(f"| {r['users']} | {r['client_processes']} | {r['requests_ok']} / {r['requests']} | **{r.get('harness_steady_output_tok_s_sum', 0):,.0f}** | "
              f"{g('srv_generation_tokens_per_s'):,.0f}{'' if full else ' (whole run¹)'} | {r.get('ttft_ms_p50', 0):,.0f} / {r.get('ttft_ms_p95', 0):,.0f} | "
              f"{r.get('itl_ms_p50', 0):.1f} / {r.get('itl_ms_p95', 0):.1f} | {g('srv_running_mean'):,.0f}{'' if full else '¹'} | "
              f"{g('srv_waiting_mean'):,.0f} / {g('srv_waiting_max'):,.0f} | {g('srv_kv_usage_max'):.3f} | "
              f"{na(r.get('gpu_sm_clock_mhz_mean', 0), '{:,.0f}')} | {na(r.get('gpu_power_w_mean', 0), '{:.0f}')} | "
              f"{na(r.get('cpu_client_pct_mean', 0), '{:.0f}')} / {na(r.get('cpu_client_pct_max', 0), '{:.0f}')} | {na(r.get('cpu_server_pct_mean', 0), '{:.0f}')} |")


CONFIGS = {   # model id -> config.json saved in a run (H3 logs) or by the T4 build (Qwen, same revision)
    "Qwen/Qwen2.5-3B-Instruct": REPO / "benchmarks/results/t4/20261031-192658_bneck/results/bneck/logs/model-config.json",
}


def config_for(model: str) -> dict:
    if model in CONFIGS:
        return json.loads(CONFIGS[model].read_text())
    name = model.replace("/", "--")
    f = next(iter(sorted(RAW.glob(f"*/*/logs/config-{name}.json"))), None)
    if f is None:
        raise FileNotFoundError(f"no saved config.json for {model}")
    return json.loads(f.read_text())


def traces(force: bool = False) -> None:
    """benchmarks/kaggle/trace_breakdown.py over every downloaded trace dir; <key>.breakdown.json next to the row."""
    sys.path.insert(0, str(REPO))
    from benchmarks.kaggle import trace_breakdown as tb
    for task in ("h2", "h3"):
        for r in rows(task):
            if r.get("kind") != "offline" or not r.get("profiler_config"):
                continue
            d = RAW.parent / Path(r["_src"]).parent
            out = d / f"{r['key']}.breakdown.json"
            if out.exists() and not force:
                continue
            files = sorted((d / f"trace-{r['key']}").glob("**/*.pt.trace.json*"), key=lambda p: p.stat().st_size, reverse=True)
            if not files:
                print(f"{r['key']}: no trace file")
                continue
            kv_bytes = 1 if "fp8" in " ".join(r.get("bench_cmd", "").split("--kv-cache-dtype")[1:2]) else 2
            model = tb.model_from_config(config_for(r["model"]), kv_bytes)
            res = tb.analyze(tb.load(files[0]), model)
            res.pop("per_step", None)
            res["trace_file"] = str(files[0].relative_to(d))
            res["kv_elem_bytes"] = kv_bytes
            out.write_text(json.dumps(res, indent=1) + "\n")
            print(f"{r['key']}: {files[0].name} -> {out.name}: {res.get('share_pct_of_window')}")


def nsys_events(db: Path) -> dict:
    """Nsight Systems SQLite export -> the Kineto-like event list trace_breakdown.analyze reads (times in us):
    NVTX ranges -> user_annotation, CUDA runtime / driver API calls -> cuda_runtime (with correlation), kernels ->
    kernel, memcpy / memset -> gpu_memcpy / gpu_memset. Column names are read from the file (PRAGMA table_info)."""
    import sqlite3
    con = sqlite3.connect(str(db))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = lambda t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
    strings = dict(con.execute("SELECT id, value FROM StringIds")) if "StringIds" in tables else {}
    evs: list[dict] = []
    if "NVTX_EVENTS" in tables:
        c = cols("NVTX_EVENTS")
        q = "SELECT start, end, text" + (", textId" if "textId" in c else ", NULL") + " FROM NVTX_EVENTS WHERE end IS NOT NULL"
        for st, en, text, tid in con.execute(q):
            name = text if text is not None else strings.get(tid, "")
            if name:
                evs.append({"ph": "X", "cat": "user_annotation", "name": name, "ts": st / 1e3, "dur": (en - st) / 1e3})
    for t in ("CUPTI_ACTIVITY_KIND_RUNTIME", "CUPTI_ACTIVITY_KIND_DRIVER"):
        if t in tables:
            for st, corr in con.execute(f"SELECT start, correlationId FROM {t}"):
                evs.append({"ph": "X", "cat": "cuda_runtime", "name": "launch", "ts": st / 1e3, "dur": 0, "args": {"correlation": corr}})
    if "CUPTI_ACTIVITY_KIND_KERNEL" in tables:
        c = cols("CUPTI_ACTIVITY_KIND_KERNEL")
        name_col = "demangledName" if "demangledName" in c else "shortName"
        for st, en, corr, nid in con.execute(f"SELECT start, end, correlationId, {name_col} FROM CUPTI_ACTIVITY_KIND_KERNEL"):
            evs.append({"ph": "X", "cat": "kernel", "name": strings.get(nid, str(nid)), "ts": st / 1e3, "dur": (en - st) / 1e3,
                        "args": {"correlation": corr}})
    for t, cat in (("CUPTI_ACTIVITY_KIND_MEMCPY", "gpu_memcpy"), ("CUPTI_ACTIVITY_KIND_MEMSET", "gpu_memset")):
        if t in tables:
            for st, en, corr in con.execute(f"SELECT start, end, correlationId FROM {t}"):
                evs.append({"ph": "X", "cat": cat, "name": cat, "ts": st / 1e3, "dur": (en - st) / 1e3, "args": {"correlation": corr}})
    return {"traceEvents": evs}


def nsys_window_breakdown(db: Path, model: dict) -> dict:
    """Time-window nsys capture without NVTX: shares of the window [first, last device event] by category
    (trace_breakdown.category), idle = window - union of device intervals, and per-step numbers with steps delimited by
    successive `_gumbel_sample_kernel` starts (one sampler launch per engine step in every vLLM trace of this build).
    A step's GEMM FLOPs are not known without the step's token count, so only times are reported."""
    import statistics as st_
    sys.path.insert(0, str(REPO))
    from benchmarks.kaggle import trace_breakdown as tb
    ev = [e for e in nsys_events(db)["traceEvents"] if e["cat"] in ("kernel", "gpu_memcpy", "gpu_memset")]
    ev.sort(key=lambda e: e["ts"])
    if not ev:
        return {"error": "no device events"}
    w0, w1 = ev[0]["ts"], max(e["ts"] + e["dur"] for e in ev)
    cat = {}
    for e in ev:
        c, _ = tb.category(e, None)
        cat[c] = cat.get(c, 0.0) + e["dur"]
    busy = tb.union_length([(e["ts"], e["ts"] + e["dur"]) for e in ev])
    span = w1 - w0
    shares = {c: round(100 * v / span, 2) for c, v in cat.items()} | {"idle": round(100 * (span - busy) / span, 2)}
    marks = [e["ts"] for e in ev if "_gumbel_sample_kernel" in e["name"]]
    steps = []
    import bisect
    starts = [e["ts"] for e in ev]
    for a, b in zip(marks, marks[1:]):
        lo, hi = bisect.bisect_left(starts, a), bisect.bisect_left(starts, b)
        seg = ev[lo:hi]
        iv = [(e["ts"], min(e["ts"] + e["dur"], b)) for e in seg]
        g = sum(e["dur"] for e in seg if tb.category(e, None)[0] == "gemm")
        at = sum(e["dur"] for e in seg if tb.category(e, None)[0] == "attention")
        steps.append({"period_us": b - a, "busy_us": tb.union_length(iv), "gemm_us": g, "attn_us": at})
    out = {"window_us": round(span, 1), "device_events": len(ev), "busy_us": round(busy, 1), "share_pct_of_window": shares,
           "category_us": {k: round(v, 1) for k, v in cat.items()}, "gap_us": tb._dist(tb.gaps([(e["ts"], e["ts"] + e["dur"]) for e in ev])),
           "top_kernels": tb._top([{"name": e["name"], "dur": e["dur"], "cat": tb.category(e, None)[0], "sub": tb.category(e, None)[1]} for e in ev], 15),
           "steps_by_sampler_kernel": len(steps)}
    if steps:
        per = sorted(x["period_us"] for x in steps)
        med = st_.median(per)
        dec = [x for x in steps if x["period_us"] <= 1.5 * med]   # long steps = prefill-mixed (chunked prefill of 8,192 tokens)
        tot = lambda k, xs: sum(x[k] for x in xs)
        out["steps"] = {"all": {"n": len(steps), "period_ms_p50": round(med / 1e3, 3), "period_ms_mean": round(st_.fmean(per) / 1e3, 3),
                                "busy_pct": round(100 * tot("busy_us", steps) / tot("period_us", steps), 2)},
                        "short (<= 1.5 x median: decode)": {"n": len(dec), "period_ms_mean": round(tot("period_us", dec) / len(dec) / 1e3, 3),
                                                            "busy_pct": round(100 * tot("busy_us", dec) / tot("period_us", dec), 2),
                                                            "idle_pct": round(100 * (1 - tot("busy_us", dec) / tot("period_us", dec)), 2),
                                                            "gemm_pct": round(100 * tot("gemm_us", dec) / tot("period_us", dec), 2),
                                                            "attn_pct": round(100 * tot("attn_us", dec) / tot("period_us", dec), 2)}}
    return out


def nsys_windows(force: bool = False) -> None:
    for r in rows("h4"):
        if r.get("kind") != "offline" or not r.get("nsys_window_s"):
            continue
        d = RAW.parent / Path(r["_src"]).parent
        db, out = d / f"{r['key']}.sqlite", d / f"{r['key']}.nsys-breakdown.json"
        if not db.exists() or (out.exists() and not force):
            print(f"{r['key']}: {'no sqlite' if not db.exists() else 'done'}")
            continue
        sys.path.insert(0, str(REPO))
        from benchmarks.kaggle import trace_breakdown as tb
        res = nsys_window_breakdown(db, tb.model_from_config(config_for(r["model"])))
        res["source"] = f"{db.name} (nsys SQLite export, window {r['nsys_window_s']} s after launch)"
        out.write_text(json.dumps(res, indent=1) + "\n")
        print(r["key"], res.get("share_pct_of_window"), res.get("steps"))


def nsys(force: bool = False) -> None:
    """trace_breakdown.analyze over every downloaded nsys SQLite export; <key>.nsys-breakdown.json next to the row."""
    sys.path.insert(0, str(REPO))
    from benchmarks.kaggle import trace_breakdown as tb
    for task in ("h2", "h3", "h4"):
        for r in rows(task):
            if r.get("kind") != "offline" or not r.get("nsys_cmd"):
                continue
            d = RAW.parent / Path(r["_src"]).parent
            db, out = d / f"{r['key']}.sqlite", d / f"{r['key']}.nsys-breakdown.json"
            if not db.exists() or (out.exists() and not force):
                print(f"{r['key']}: {'no sqlite' if not db.exists() else 'done'}")
                continue
            kv_bytes = 1 if "fp8" in " ".join(r.get("bench_cmd", "").split("--kv-cache-dtype")[1:2]) else 2
            res = tb.analyze(nsys_events(db), tb.model_from_config(config_for(r["model"]), kv_bytes))
            res.pop("per_step", None)
            res["source"] = f"{db.name} (nsys SQLite export)"
            out.write_text(json.dumps(res, indent=1) + "\n")
            print(f"{r['key']}: {res.get('share_pct_of_window')} {(res.get('steps') or {}).get('decode_only')}")


def model_flops(model: str) -> dict:
    """Linear + lm_head parameters per token from config.json (CALCULATED), FLOP per decode token = 2 x params."""
    cfg = config_for(model)
    sys.path.insert(0, str(REPO))
    from benchmarks.kaggle import trace_breakdown as tb
    t = tb.model_from_config(cfg)
    p_lin, p_lm = tb.linear_params(t), tb.lm_head_params(t)
    return {"p_lin": p_lin, "p_lm": p_lm, "flop_per_decode_token": 2 * (p_lin + p_lm), "kv_bytes_per_token_bf16": t["kv_bytes_per_token"],
            "weight_bytes_bf16": 2 * (p_lin + p_lm)}


def waterfall(breakdown: Path, measured: dict, model: str, peak_tflops: float = DATASHEET["bf16_tflops"],
              peak_mhz: float = DATASHEET["max_sm_mhz_measured"], prof_clk: float | None = None) -> dict:
    """Build 16 G5 chain for one measured row, factors from one breakdown (decode-only steps, `all` steps).
    GEMM efficiency is per GHz of the profiled run's clock (assumed clock-independent, as in Build 16)."""
    b = json.loads(breakdown.read_text())
    dec, allst = b["steps"]["decode_only"], b["steps"]["all"]
    busy, gemm, attn = dec["busy_pct"], dec["gemm_pct"], dec["attn_pct"]
    other = busy - gemm - attn
    clk = prof_clk
    eta = (dec["gemm_tflops_calculated"] / (clk / 1000)) / (peak_tflops / (peak_mhz / 1000))
    f = model_flops(model)
    d0 = peak_tflops * 1e12 / f["flop_per_decode_token"]
    factors = {"clock": measured["smi_clocks_sm_mean"] / peak_mhz, "gemm_efficiency": eta, "attention": (gemm + other) / busy,
               "other_kernels": gemm / (gemm + other), "idle": busy / 100, "prompt_share": allst["gen_tokens_per_s_calculated"] / dec["gen_tokens_per_s_calculated"]}
    labels = {"clock": f"× SM clock {measured['smi_clocks_sm_mean']:,.0f} / {peak_mhz:,.0f} MHz",
              "gemm_efficiency": "× GEMM efficiency per clock (in vLLM, decode steps)", "attention": "− attention kernel time",
              "other_kernels": "− norm / activation / sampling / memcpy time", "idle": "− GPU idle between kernels",
              "prompt_share": "− prompt (prefill) steps"}
    chain, v = [(f"datasheet decode ceiling ({peak_tflops:.0f} TFLOP/s ÷ {f['flop_per_decode_token'] / 1e9:.2f} GFLOP per token)", d0)], d0
    for k in labels:
        v *= factors[k]
        chain.append((labels[k], v))
    return {"breakdown": str(breakdown.relative_to(RAW.parent)), "profile_clock_mhz": clk, "factors": factors, "chain": chain,
            "predicted": v, "measured": measured["output_tok_s"], "measured_key": measured["key"], "measured_run": measured["run_id"],
            "residual_pct": 100 * (measured["output_tok_s"] / v - 1), "inputs": {**f, "decode": dec, "all": allst}}


def print_waterfall(w: dict) -> None:
    print(f"| step | factor | tok/s after |\n|---|---:|---:|\n| {w['chain'][0][0]} | — | {w['chain'][0][1]:,.0f} |")
    for (lab, v), k in zip(w["chain"][1:], w["factors"]):
        print(f"| {lab} | {w['factors'][k]:.3f} | {v:,.0f} |")
    print(f"| **measured** (`{w['measured_key']}`, {w['measured_run']}) | | **{w['measured']:,.1f}** |")
    print(f"| **residual (unexplained)** | **{w['residual_pct']:+.1f} %** | |")


if __name__ == "__main__":
    for sec in sys.argv[1:]:
        globals()[sec]()
