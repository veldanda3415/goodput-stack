"""GPU-time breakdown of a vLLM worker torch-profiler trace (Kineto chrome trace, .json or .json.gz).

    python -m benchmarks.kaggle.trace_breakdown TRACE.pt.trace.json.gz [--out summary.json] [--kernels kernels.csv.gz]

What the trace must contain (vLLM 0.31.0, `--profiler-config '{"profiler": "torch", "detailed_trace_annotation": true,
"torch_profiler_with_stack": false, ...}'` and VLLM_CUSTOM_SCOPES_FOR_PROFILING=1):
  - CPU `user_annotation` "execute_<T>_context_<c>(sq..)_generation_<g>(sq..)" around every engine step's
    execute_model (vllm/v1/worker/gpu_worker.py annotate_profile; T = scheduled tokens, c / g = context / generation
    requests); "gpu_model_runner: forward / postprocess / sample / ..." scopes (vllm/v1/worker/gpu_model_runner.py)
  - `cuda_runtime` / `cuda_driver` (Triton's cuLaunchKernel) launch events and `kernel` / `gpu_memcpy` / `gpu_memset` device events joined by args.correlation
    (a CUDA-graph replay is one cudaGraphLaunch whose correlation id all its kernels carry)

Method:
  - Each device event is joined to its launch (correlation id) and assigned to the step whose execute_ annotation
    started last before the launch, and to the CPU scope (forward / postprocess / sample / ...) containing the launch.
  - Category per device event, first match wins: memcpy (gpu_memcpy / gpu_memset); dequant (awq / marlin dequantize);
    gemm (kernel name, GEMM_RE); attention (ATTN_RE); sampling (any non-GEMM kernel launched inside the `sample` or
    `postprocess` scope, or named like a sampler kernel, SAMPLE_RE; vLLM 0.31.0 wrote no runner scopes in the
    traces of run 20261031-192649_bneck, so the name rule is the one that applies); elementwise / norm / activation / other (the rest, sub-split by name).
  - Window = from the first device event of the first complete step to the first device event of the last step (the
    last step is dropped: it may be cut by the profiler stop). Shares are of window time; busy = union of device
    intervals; idle = window - busy (gaps between kernels, inside and between steps). Category sums can exceed busy
    when streams overlap; the overlap is reported.
  - GEMM rate (CALCULATED): linear-layer FLOPs of a step = 2 x (Qwen2.5-3B linear params per token) x T + 2 x
    lm_head params x (c + g) [one logits row per scheduled request], over the summed GEMM kernel time of the step.
    CUDA-graph padding is not in T, so this is the rate of useful work.
  - Per shape: in decode-only steps whose GEMM kernels number 36 x 4 + 1, kernels are taken in launch order as
    [qkv, o, gate_up, down] x 36 layers + lm_head.
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

GEMM_RE = re.compile(r"gemm|gemv|xmma|s1688|h1688|s884|h884|splitKreduce|cublas|cutlass", re.I)
DEQUANT_RE = re.compile(r"dequant", re.I)
ATTN_RE = re.compile(r"attention|attn|flash|paged|reshape_and_cache|unified_|reduce_segments|fmha|flex", re.I)
# checked before GEMM_RE: FlashAttention-3 (sm_90) kernels are cutlass templates, e.g. "cutlass::device_kernel<flash::...>"
ATTN_FIRST_RE = re.compile(r"flash::|FlashAttn|flash_fwd|flash_attn|fmha", re.I)
NORM_RE = re.compile(r"rms|norm|rsqrt", re.I)
ACT_RE = re.compile(r"silu|act_and_mul|gelu|swiglu", re.I)
ROPE_RE = re.compile(r"rotary|rope", re.I)
SAMPLE_RE = re.compile(r"sampl|gumbel|argmax|topk|top_k|logprob|penalt|multinomial", re.I)
PREP_RE = re.compile(r"prepare|gather_block|slot_mapping|combine_sampled|num_sampled", re.I)
STEP_RE = re.compile(r"^execute_(?:(\d+)_)?context_(\d+)\((?:sq)?(\d+)[^)]*\)_generation_(\d+)\((?:sq)?(\d+)")
KV_BYTES_PER_TOKEN = 36 * 2 * 2 * 128 * 2   # Qwen2.5-3B fp16 KV: layers x (K, V) x KV heads x head_dim x 2 B
SCOPES = ("forward", "postprocess", "sample", "preprocess", "bookkeep", "draft", "eplb", "ModelRunnerOutput")

# Qwen2.5-3B-Instruct (config.json @ aa8e7253): per layer qkv 2048x2560, o 2048x2048, gate_up 2048x22016, down 11008x2048
QWEN3B = {"layers": 36, "shapes": [("qkv", 2048, 2560), ("o", 2048, 2048), ("gate_up", 2048, 22016), ("down", 11008, 2048)],
          "lm_head": (2048, 151936), "kv_bytes_per_token": KV_BYTES_PER_TOKEN}


def model_from_config(cfg: dict, kv_elem_bytes: int = 2) -> dict:
    """The same table for any Llama / Qwen2-style config.json; kv_elem_bytes 1 for an FP8 KV cache."""
    h, heads = cfg["hidden_size"], cfg["num_attention_heads"]
    kvh = cfg.get("num_key_value_heads", heads)
    hd = cfg.get("head_dim") or h // heads
    inter, layers = cfg["intermediate_size"], cfg["num_hidden_layers"]
    return {"layers": layers, "shapes": [("qkv", h, (heads + 2 * kvh) * hd), ("o", heads * hd, h), ("gate_up", h, 2 * inter),
                                         ("down", inter, h)],
            "lm_head": (h, cfg["vocab_size"]), "kv_bytes_per_token": layers * 2 * kvh * hd * kv_elem_bytes}


def linear_params(model: dict = QWEN3B) -> int:
    return model["layers"] * sum(k * n for _, k, n in model["shapes"])


def lm_head_params(model: dict = QWEN3B) -> int:
    k, n = model["lm_head"]
    return k * n


def parse_step(name: str) -> dict | None:
    """execute_ annotation -> {tokens, ctx_reqs, ctx_tokens, gen_reqs, gen_tokens} (detailed or simple format)."""
    m = STEP_RE.match(name)
    if not m:
        return None
    total, c, ct, g, gt = m.groups()
    ct, gt = int(ct), int(gt)
    sk = [int(x) for x in re.findall(r"sk(\d+)sqsq", name)]   # detailed format: KV length summed over requests (ctx, gen)
    return {"tokens": int(total) if total else ct + gt, "ctx_reqs": int(c), "ctx_tokens": ct, "gen_reqs": int(g), "gen_tokens": gt,
            "kv_tokens": sum(sk) if len(sk) == 2 else None}


def load(path: str | Path) -> dict:
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt") as f:
        return json.load(f)


def category(ev: dict, scope: str | None) -> tuple[str, str]:
    """(category, subcategory) of one device event."""
    cat, name = ev.get("cat", ""), ev.get("name", "")
    if cat in ("gpu_memcpy", "gpu_memset"):
        return "memcpy", cat
    if DEQUANT_RE.search(name):
        return "dequant", "dequant"
    if ATTN_FIRST_RE.search(name):
        return "attention", "attention"
    if GEMM_RE.search(name):
        return "gemm", "lm_head_or_logits" if scope in ("postprocess", "sample") else "linear"
    if ATTN_RE.search(name):
        return "attention", "kv_write" if "reshape_and_cache" in name else "attention"
    if scope in ("sample", "postprocess"):
        return "sampling", scope
    if SAMPLE_RE.search(name):
        return "sampling", "by_name"
    if PREP_RE.search(name):
        return "elementwise", "input_prep"
    if NORM_RE.search(name):
        return "elementwise", "norm"
    if ACT_RE.search(name):
        return "elementwise", "activation"
    if ROPE_RE.search(name):
        return "elementwise", "rotary"
    return "elementwise", "other"


def union_length(intervals: list[tuple[float, float]]) -> float:
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def gaps(intervals: list[tuple[float, float]]) -> list[float]:
    out, cur_e = [], None
    for s, e in sorted(intervals):
        if cur_e is not None and s > cur_e:
            out.append(s - cur_e)
        cur_e = e if cur_e is None else max(cur_e, e)
    return out


def analyze(trace: dict, model: dict = QWEN3B) -> dict:
    evs = [e for e in trace.get("traceEvents", []) if e.get("ph") == "X"]
    steps = sorted((e for e in evs if e.get("cat") == "user_annotation" and parse_step(e.get("name", ""))), key=lambda e: e["ts"])
    if len(steps) < 3:
        return {"error": f"{len(steps)} execute_ step annotations in the trace (need >= 3)"}
    step_ts = [s["ts"] for s in steps]
    scopes = sorted(((e["ts"], e["ts"] + e.get("dur", 0), e["name"].split(": ", 1)[1]) for e in evs
                     if e.get("cat") == "user_annotation" and e.get("name", "").startswith("gpu_model_runner: ")))
    scope_starts = [s[0] for s in scopes]
    launch = {}
    for e in evs:
        if e.get("cat") in ("cuda_runtime", "cuda_driver") and "correlation" in (e.get("args") or {}):
            launch[e["args"]["correlation"]] = e["ts"]
    dev = [e for e in evs if e.get("cat") in ("kernel", "gpu_memcpy", "gpu_memset")]
    unjoined = 0
    rows = []
    for e in dev:
        lt = launch.get((e.get("args") or {}).get("correlation"))
        if lt is None:
            unjoined += 1
            lt = e["ts"]   # fallback: device time (still ordered after its launch)
        si = bisect.bisect_right(step_ts, lt) - 1
        j = bisect.bisect_right(scope_starts, lt) - 1
        scope = None
        for jj in range(j, max(j - 3, -1), -1):   # the runner's scopes follow each other; look back a few
            if scopes[jj][0] <= lt <= scopes[jj][1]:
                scope = scopes[jj][2]
                break
        cat, sub = category(e, scope)
        rows.append({"step": si, "ts": e["ts"], "dur": e.get("dur", 0), "name": e.get("name", ""), "cat": cat, "sub": sub,
                     "scope": scope, "launch_ts": lt})
    rows.sort(key=lambda r: r["ts"])
    first_dev = {}
    for r in rows:
        if r["step"] >= 0 and r["step"] not in first_dev:
            first_dev[r["step"]] = r["ts"]
    complete = sorted(s for s in first_dev if s + 1 in first_dev)
    if not complete:
        return {"error": "no complete step with device activity"}
    w0, w1 = first_dev[complete[0]], first_dev[complete[-1] + 1]
    span = w1 - w0
    inw = [r for r in rows if w0 <= r["ts"] < w1]
    ivals = [(r["ts"], min(r["ts"] + r["dur"], w1)) for r in inw]
    busy = union_length(ivals)
    cat_us = Counter()
    sub_us = Counter()
    for r in inw:
        cat_us[r["cat"]] += r["dur"]
        sub_us[f"{r['cat']}/{r['sub']}"] += r["dur"]
    shares = {c: round(100 * v / span, 2) for c, v in cat_us.items()}
    shares["idle"] = round(100 * (span - busy) / span, 2)
    # per step
    by_step = defaultdict(list)
    for r in inw:
        by_step[r["step"]].append(r)
    lin, lmh = linear_params(model), lm_head_params(model)
    kvb = model.get("kv_bytes_per_token", KV_BYTES_PER_TOKEN)
    starts = [r["ts"] for r in inw]
    max_dur = max((r["dur"] for r in inw), default=0)
    per_step = []
    for si in complete:
        info = parse_step(steps[si]["name"])
        rs = by_step.get(si, [])
        s0, s1 = first_dev[si], first_dev[si + 1]
        # busy = every device interval (whichever step launched it) clipped to this step's window
        lo = bisect.bisect_left(starts, s0 - max_dur)
        iv = [(max(r["ts"], s0), min(r["ts"] + r["dur"], s1)) for r in inw[lo:bisect.bisect_left(starts, s1)]
              if r["ts"] + r["dur"] > s0]
        gemm_k = [r for r in sorted(rs, key=lambda r: r["launch_ts"]) if r["cat"] == "gemm"]
        gemm_t = sum(r["dur"] for r in gemm_k)
        flops = 2 * lin * info["tokens"] + 2 * lmh * (info["ctx_reqs"] + info["gen_reqs"])
        nxt = steps[si + 1]["ts"] if si + 1 < len(steps) else None
        attn_t = sum(r["dur"] for r in rs if r["cat"] == "attention" and r["sub"] == "attention")
        per_step.append({"step": si, **info, "gpu_period_us": s1 - s0, "busy_us": union_length(iv),
                         "attn_kernel_us": attn_t,
                         "attn_kv_gb_s_calculated": (info["kv_tokens"] * kvb / attn_t / 1e3)
                         if info.get("kv_tokens") and attn_t else None,
                         "gemm_us": gemm_t, "gemm_kernels": len(gemm_k),
                         "attn_us": sum(r["dur"] for r in rs if r["cat"] == "attention"),
                         "linear_flops": flops, "gemm_tflops": flops / gemm_t / 1e6 if gemm_t else None,
                         "cpu_execute_us": steps[si].get("dur"), "cpu_period_us": (nxt - steps[si]["ts"]) if nxt else None,
                         "_gemms": gemm_k})
    out: dict = {"window_us": round(span, 1), "steps_in_window": len(complete), "device_events": len(rows),
                 "device_events_in_window": len(inw), "unjoined_device_events": unjoined,
                 "busy_us": round(busy, 1), "category_us": {k: round(v, 1) for k, v in cat_us.items()},
                 "subcategory_us": {k: round(v, 1) for k, v in sub_us.most_common()},
                 "share_pct_of_window": shares, "overlap_us": round(sum(cat_us.values()) - busy, 1),
                 "gap_us": _dist([g for g in gaps(ivals)]),
                 "top_kernels": _top(inw, 25)}
    out["steps"] = _step_summary(per_step, kvb)
    out["model_table"] = {k: v for k, v in model.items()}
    out["per_shape"] = _per_shape(per_step, model)
    for p in per_step:
        p.pop("_gemms")
    out["per_step"] = per_step
    return out


def _dist(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(p * len(s)))]
    return {"n": len(s), "sum": round(sum(s), 1), "p50": round(q(0.5), 2), "p90": round(q(0.9), 2), "p99": round(q(0.99), 2),
            "max": round(s[-1], 2)}


def _top(rows: list[dict], n: int) -> list[dict]:
    t, c, cat = Counter(), Counter(), {}
    for r in rows:
        t[r["name"]] += r["dur"]
        c[r["name"]] += 1
        cat[r["name"]] = f"{r['cat']}/{r['sub']}"
    total = sum(t.values()) or 1
    return [{"name": k[:160], "category": cat[k], "us": round(v, 1), "count": c[k], "pct_of_device_time": round(100 * v / total, 2)}
            for k, v in t.most_common(n)]


def _step_summary(per_step: list[dict], kv_bytes_per_token: int = KV_BYTES_PER_TOKEN) -> dict:
    out = {}
    for kind, sel in (("all", lambda p: True), ("decode_only", lambda p: p["ctx_reqs"] == 0),
                      ("mixed", lambda p: p["ctx_reqs"] > 0)):
        ps = [p for p in per_step if sel(p)]
        if not ps:
            continue
        period = sum(p["gpu_period_us"] for p in ps)
        gemm = sum(p["gemm_us"] for p in ps)
        flops = sum(p["linear_flops"] for p in ps)
        cpu_ex = [p["cpu_execute_us"] for p in ps if p["cpu_execute_us"] is not None]
        cpu_per = [p["cpu_period_us"] for p in ps if p["cpu_period_us"] is not None]
        out[kind] = {"steps": len(ps), "tokens_per_step_mean": round(statistics.fmean(p["tokens"] for p in ps), 1),
                     "tokens_mode": Counter(p["tokens"] for p in ps).most_common(1)[0][0],
                     "gpu_period_ms_mean": round(period / len(ps) / 1e3, 3),
                     "gpu_period_ms_p50": round(statistics.median(p["gpu_period_us"] for p in ps) / 1e3, 3),
                     "busy_pct": round(100 * sum(p["busy_us"] for p in ps) / period, 2),
                     "idle_pct": round(100 * (1 - sum(p["busy_us"] for p in ps) / period), 2),
                     "gemm_pct": round(100 * gemm / period, 2), "attn_pct": round(100 * sum(p["attn_us"] for p in ps) / period, 2),
                     "gemm_tflops_calculated": round(flops / gemm / 1e6, 3) if gemm else None,
                     "gemm_kernels_per_step_mode": Counter(p["gemm_kernels"] for p in ps).most_common(1)[0][0],
                     "kv_tokens_per_step_mean": round(statistics.fmean(p["kv_tokens"] for p in ps), 1) if all(p.get("kv_tokens") for p in ps) else None,
                     "attn_kernel_ms_mean": round(statistics.fmean(p["attn_kernel_us"] for p in ps) / 1e3, 3),
                     "attn_kv_read_gb_s_calculated": round(sum(p["kv_tokens"] for p in ps) * kv_bytes_per_token
                                                          / sum(p["attn_kernel_us"] for p in ps) / 1e3, 1)
                     if all(p.get("kv_tokens") for p in ps) and sum(p["attn_kernel_us"] for p in ps) else None,
                     "cpu_execute_ms_p50": round(statistics.median(cpu_ex) / 1e3, 3) if cpu_ex else None,
                     "cpu_period_ms_p50": round(statistics.median(cpu_per) / 1e3, 3) if cpu_per else None,
                     "gen_tokens_per_s_calculated": round(sum(p["gen_tokens"] for p in ps) / (period / 1e6), 1)}
    return out


def _per_shape(per_step: list[dict], model: dict) -> dict:
    n_layers, shapes = model["layers"], model["shapes"]
    want = n_layers * len(shapes) + 1
    acc: dict = defaultdict(lambda: {"us": 0.0, "flops": 0, "kernels": Counter()})
    used = Counter()
    for p in per_step:
        if p["ctx_reqs"] or len(p["_gemms"]) != want:
            continue
        used[p["tokens"]] += 1
        m = p["tokens"]
        for i, r in enumerate(p["_gemms"]):
            if i == want - 1:
                name, k, n = "lm_head", *model["lm_head"]
                mm = p["gen_reqs"]
            else:
                name, k, n = shapes[i % len(shapes)]
                mm = m
            a = acc[(m, name)]
            a["us"] += r["dur"]
            a["flops"] += 2 * mm * k * n
            a["kernels"][r["name"][:120]] += 1
    out = {"rule": f"decode-only steps with exactly {want} GEMM kernels, launch order [qkv, o, gate_up, down] x {n_layers} + lm_head",
           "steps_used_by_tokens": dict(used), "shapes": []}
    for (m, name), a in sorted(acc.items()):
        out["shapes"].append({"m": m, "shape": name, "us_total": round(a["us"], 1), "tflops_calculated": round(a["flops"] / a["us"] / 1e6, 3),
                              "kernel_names": dict(a["kernels"].most_common(3))})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("--out")
    ap.add_argument("--keep-steps", action="store_true", help="keep the per_step list in --out")
    ap.add_argument("--config", help="model config.json (default: the Qwen2.5-3B table)")
    ap.add_argument("--kv-elem-bytes", type=int, default=2, help="1 for an FP8 KV cache")
    a = ap.parse_args()
    model = model_from_config(json.loads(Path(a.config).read_text()), a.kv_elem_bytes) if a.config else QWEN3B
    res = analyze(load(a.trace), model)
    if not a.keep_steps:
        res.pop("per_step", None)
    text = json.dumps(res, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(json.dumps({k: res.get(k) for k in ("window_us", "steps_in_window", "share_pct_of_window", "steps", "error")}, indent=1))


if __name__ == "__main__":
    main()
