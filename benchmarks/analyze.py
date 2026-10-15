"""T4 results -> charts (PNG), benchmarks/results/t4/summary.md and benchmarks/kv_capacity_table.md.

    .venv/bin/python benchmarks/analyze.py
    .venv/bin/python benchmarks/analyze.py --price-json benchmarks/results/t4/pricing/azure-NC4as_T4_v3-eastus.json

Input: every benchmarks/results/t4/<run-id>/results/<stage>/<stage>.jsonl written by
benchmarks/kaggle/t4_notebook.py. Rows are merged per stage by `key`; a later run overrides an earlier
one, and every table row links the JSONL it came from. Nothing here is measured; it only reshapes rows.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
T4 = REPO / "benchmarks" / "results" / "t4"
CHARTS = T4 / "charts"
# Reference categorical palette (dataviz skill, references/palette.md), slots in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"

# Logged before any T4 run (task brief); checked, never tuned.
PRED = {"decode_tok_s_max": 50, "decode_tok_s_expect": "30-35", "kv_tokens": 55_000,
        "kv_bytes_per_token_llama32_3b": 114_688, "gpu_mem_util": 0.90}


def load(stage: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for f in sorted(T4.glob(f"*_{stage}/results/{stage}/{stage}.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r["_src"] = str(f.relative_to(REPO))
                rows[r["key"]] = r
    return rows


def link(r: dict, base: Path) -> str:
    rel = Path(r["_src"])
    return f"[{rel.parts[3]}]({Path(*(['..'] * len(base.relative_to(REPO).parts))) / rel})"


def fmt(v, nd=1) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def kv_bytes_per_token(cfg: dict, dtype_bytes: int = 2) -> tuple[int, str]:
    layers, kvh = cfg["num_hidden_layers"], cfg.get("num_key_value_heads") or cfg["num_attention_heads"]
    hd = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
    b = 2 * layers * kvh * hd * dtype_bytes
    return b, f"2 (K,V) × {layers} layers × {kvh} KV heads × {hd} head_dim × {dtype_bytes} B (FP16) = {b:,} B/token"


# ---------------------------------------------------------------- charts

def style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=MUTED)


def line_chart(path: Path, title: str, ylabel: str, series: list[tuple[str, list, list, str, str]], logx=True) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 4), facecolor=SURFACE)
    for name, xs, ys, color, ls in series:
        ax.plot(xs, ys, color=color, linestyle=ls, linewidth=2, marker="o", markersize=5, label=name)
        if xs:
            ax.annotate(name, (xs[-1], ys[-1]), textcoords="offset points", xytext=(6, 0), color=INK, fontsize=8, va="center")
    if logx:
        ax.set_xscale("log", base=2)
        xs_all = sorted({x for s in series for x in s[1]})
        ax.set_xticks(xs_all, [str(x) for x in xs_all])
    style(ax, title, "concurrent clients (closed loop)", ylabel)
    if len(series) >= 2:
        ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def bar_chart(path: Path, title: str, ylabel: str, names: list[str], values: list[float]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 3.6), facecolor=SURFACE)
    bars = ax.bar(names, values, color=SERIES[0], width=0.55, edgecolor=SURFACE, linewidth=2)
    for b, v in zip(bars, values):
        ax.annotate(f"{v:.1f}", (b.get_x() + b.get_width() / 2, v), textcoords="offset points", xytext=(0, 3),
                    ha="center", color=INK, fontsize=8)
    style(ax, title, "", ylabel)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- sections

def section_baseline(rows: dict, out: list[str], base: Path) -> dict:
    if not rows:
        out += ["## Task 1 — baseline", "", "No baseline rows yet.", ""]
        return {}
    out += ["## Task 1 — baseline serve", ""]
    attempts = [r for k, r in rows.items() if k.startswith("attempt-")]
    out += ["### vLLM version attempts (latest first)", "", "| vLLM | result | torch after install | startup s | detail | source |", "|---|---|---|---:|---|---|"]
    for r in attempts:
        detail = "; ".join(r.get("error_lines", [])[-2:])[:300] or r.get("pip_tail", "")[:200] or (r.get("attention_backend_lines") or [""])[0][:200]
        out.append(f"| {r['vllm_version_requested']} | {r['result']} | {r.get('torch_after_install', '—')} | {fmt(r.get('startup_s'))} | {detail.replace('|', '/')} | {link(r, base)} |")
    out.append("")
    st, dec = rows.get("startup"), rows.get("decode-batch1")
    facts: dict = {}
    if st:
        cfg = st.get("model_config_json") or {}
        facts["model"] = st["model"]
        out += [f"Model: `{st['model']}` @ `{st.get('model_revision')}` — {st.get('model_choice')}", "",
                f"Serving flags: `{' '.join(st.get('serving_flags', []))}` · vLLM {st.get('vllm_version')} · torch {st.get('torch')}", "",
                "### Startup facts (from the server log and /metrics `vllm:cache_config_info`)", "",
                "| fact | value | where |", "|---|---|---|",
                f"| num GPU blocks | {fmt(st.get('num_gpu_blocks'))} | `vllm:cache_config_info` label (fallback: log) |",
                f"| block size | {fmt(st.get('block_size'))} | `vllm:cache_config_info` label |",
                f"| blocks × block size | {fmt(st.get('blocks_x_block_size'))} tokens | computed |",
                f"| GPU KV cache size | {fmt(st.get('gpu_kv_cache_tokens'))} tokens | log `GPU KV cache size:` |",
                f"| available KV memory | {fmt(st.get('available_kv_gib'), 2)} GiB | log `Available KV cache memory:` |",
                f"| model weights | {fmt(st.get('model_weights_gib'), 2)} GiB | log `Model loading took` |",
                f"| max concurrency @ {fmt(st.get('max_concurrency_len_log'))} tok | {fmt(st.get('max_concurrency_log'), 2)}× | log `Maximum concurrency for` |",
                f"| attention backend | {'<br>'.join(x.replace('|', '/') for x in st.get('attention_backend_lines', [])[:3]) or '—'} | log |", ""]
        facts |= {k: st.get(k) for k in ("num_gpu_blocks", "block_size", "blocks_x_block_size", "gpu_kv_cache_tokens", "available_kv_gib", "model_weights_gib")}
        if cfg.get("num_hidden_layers"):
            b, formula = kv_bytes_per_token(cfg)
            facts["kv_bytes_per_token"] = b
            out += [f"KV bytes/token from `config.json`: {formula}.", ""]
            if st.get("available_kv_gib"):
                facts["kv_tokens_from_mem"] = int(st["available_kv_gib"] * 2**30 / b)
                out += [f"Consistency check (computed): available KV {st['available_kv_gib']} GiB / {b:,} B = {facts['kv_tokens_from_mem']:,} tokens.", ""]
    if dec:
        runs = [r.get("decode_tok_s_usage") for r in dec.get("decode_runs", [])]
        facts |= {"decode_median": dec.get("decode_tok_s_median"), "decode_spread": dec.get("decode_spread_pct")}
        out += ["### Batch-1 decode", "",
                f"{dec.get('decode_n')} streamed runs, prompt “{dec.get('decode_prompt')}”, max_tokens {dec.get('decode_max_tokens')}, ignore_eos, temperature 0. "
                f"Decode tok/s = (completion_tokens − 1) / (last − first content chunk).", "",
                f"**median {fmt(dec.get('decode_tok_s_median'), 2)} tok/s**, min {fmt(dec.get('decode_tok_s_min'), 2)}, max {fmt(dec.get('decode_tok_s_max'), 2)}, "
                f"spread {fmt(dec.get('decode_spread_pct'), 2)} % · runs: {', '.join(fmt(x, 2) for x in runs)} · TTFT median {fmt(dec.get('ttft_s_median'), 3)} s · {link(dec, base)}", ""]
    for k in ("chat-nonstream", "chat-stream"):
        r = rows.get(k)
        if r:
            out.append(f"- `{k}`: HTTP {r.get('status')}, usage {r.get('usage')}, content “{(r.get('content_head') or '')[:60]}”")
    mn = rows.get("metric-names")
    if mn:
        out += ["", "### /metrics names by role (from the `# TYPE` lines of the idle scrape)", "", "| role | metric(s) |", "|---|---|"]
        for role, names in mn["roles"].items():
            out.append(f"| {role} | {', '.join(f'`{n}`' for n in names) or '— (not exported)'} |")
        out += ["", "Raw scrapes: `logs/metrics-idle.txt`, `logs/metrics-load.txt` (c=16 load), `logs/metrics-after.txt` in the run dir.", ""]
    return facts


def section_predictions(f: dict, out: list[str]) -> None:
    if not f:
        return
    llama = "Llama-3.2-3B" in (f.get("model") or "")
    b = f.get("kv_bytes_per_token")
    carried = int(PRED["kv_tokens"] * PRED["kv_bytes_per_token_llama32_3b"] / b) if b and not llama else None
    out += ["## Predictions vs measured", "",
            f"Measured model: `{f.get('model')}`." + ("" if llama else " The predictions were made for Llama-3.2-3B; the KV rows are restated for this model from its config.json (formula above)."), "",
            "| quantity | predicted | measured | why different |", "|---|---|---|---|",
            f"| batch-1 decode tok/s | ≤ {PRED['decode_tok_s_max']} (expect {PRED['decode_tok_s_expect']}) | {fmt(f.get('decode_median'), 2)} | see notes |",
            f"| KV bytes/token | {PRED['kv_bytes_per_token_llama32_3b']:,} (Llama-3.2-3B) | {fmt(b)} (config.json) | {'same model' if llama else 'different model: fewer layers×KV heads×head_dim'} |",
            f"| KV pool tokens @ 0.90 | ≈ {PRED['kv_tokens']:,}" + (f" → {carried:,} restated (same KV bytes, this model's B/token)" if carried else "") +
            f" | {fmt(f.get('gpu_kv_cache_tokens'))} (log) | see notes |",
            f"| GPU blocks × block size ≈ KV pool | ≈ KV pool | {fmt(f.get('num_gpu_blocks'))} × {fmt(f.get('block_size'))} = {fmt(f.get('blocks_x_block_size'))} | — |", ""]


def section_kv(rows: dict, base_md: Path) -> list[str]:
    cells = sorted((r for r in rows.values() if r.get("kind") == "kv_cell"),
                   key=lambda r: (r["gpu_memory_utilization"], r["max_model_len"]))
    out = ["# KV capacity on one T4 — 8B AWQ INT4", "",
           "Generated by `benchmarks/analyze.py` from `kvgrid.jsonl`; do not edit by hand.", ""]
    if not cells:
        return out + ["No kvgrid rows yet.", ""]
    r0 = cells[0]
    out += [f"Model `{r0['model']}` @ `{r0.get('model_revision')}` · vLLM {r0.get('vllm_version')} · {r0.get('gpu')} · driver {r0.get('driver')} · "
            f"flags `--dtype half --no-enable-prefix-caching` + the two swept flags.", "",
            "| --gpu-memory-utilization | --max-model-len | started | GPU blocks | block size | KV tokens | max concurrent full-length seqs | source of that column | weights GiB | KV GiB | error | row |",
            "|---:|---:|---|---:|---:|---:|---:|---|---:|---:|---|---|"]
    for r in cells:
        err = "; ".join(r.get("error_lines", [])[-2:]).replace("|", "/")[:400] if not r.get("started") else ""
        out.append(f"| {r['gpu_memory_utilization']} | {r['max_model_len']} | {'yes' if r.get('started') else 'no'} | {fmt(r.get('num_gpu_blocks'))} | "
                   f"{fmt(r.get('block_size'))} | {fmt(r.get('kv_tokens'))} | {fmt(r.get('max_full_len_seqs'), 2)} | {r.get('max_full_len_seqs_source', '—')} | "
                   f"{fmt(r.get('model_weights_gib'), 2)} | {fmt(r.get('available_kv_gib'), 2)} | {err} | {link(r, base_md)} |")
    return out + [""]


def section_sweep(rows: dict, out: list[str], base: Path) -> None:
    closed = [r for r in rows.values() if r.get("kind") == "closed_loop"]
    if not closed:
        out += ["## Task 4 — concurrency sweep", "", "No sweep rows yet.", ""]
        return
    r0 = closed[0]
    out += ["## Task 4 — concurrency sweep", "",
            f"Model `{r0['model']}` @ `{r0.get('model_revision')}` ({r0.get('model_choice')}) · vLLM {r0.get('vllm_version')} · prefix caching: {r0.get('prefix_caching')}.",
            f"Client: benchmarks/harness, `/v1/completions` streamed, {r0['client']['prompt_tokens']} prompt tokens (unique random words, uuid prefix), "
            f"max_tokens {r0['client']['max_tokens']} ± {int(r0['client']['max_tokens_jitter'] * 100)} %, ignore_eos, start jitter {r0['client']['start_jitter_s']} s, "
            f"requests max(20, 4×c), 2 warmup. TTFT/ITL client-side (first token chunk / chunk gaps); srv_* = vLLM /metrics sampled at 1 Hz; gpu_* = NVML at 1 Hz.", "",
            "| max-num-seqs | c | ok | err | TTFT p50 / p95 ms | ITL p50 / p95 ms | steady out tok/s | req/s | running max | waiting max | KV usage max | preempt | GPU util mean % | power mean W | row |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    by_mns: dict[str, list[dict]] = {}
    for r in sorted(closed, key=lambda r: (str(r["max_num_seqs"]), r["concurrency"])):
        by_mns.setdefault(str(r["max_num_seqs"]), []).append(r)
        out.append(f"| {r['max_num_seqs']} | {r['concurrency']} | {r.get('requests_ok')} | {r.get('errors')} | {fmt(r.get('ttft_ms_p50'), 0)} / {fmt(r.get('ttft_ms_p95'), 0)} | "
                   f"{fmt(r.get('itl_ms_p50'))} / {fmt(r.get('itl_ms_p95'))} | {fmt(r.get('steady_output_tok_s'))} | {fmt(r.get('req_s'), 2)} | "
                   f"{fmt(r.get('srv_running_max'), 0)} | {fmt(r.get('srv_waiting_max'), 0)} | {fmt(r.get('srv_kv_usage_max'), 3)} | {fmt(r.get('srv_preemptions'), 0)} | "
                   f"{fmt(r.get('gpu_util_gpu_pct_mean'))} | {fmt(r.get('gpu_power_w_mean'))} | {link(r, base)} |")
    out.append("")
    knee = rows.get("knee")
    if knee:
        out += [f"Knee ({knee['rule']}): c = {knee['knee_concurrency']}, {knee['knee_req_s']} req/s, max steady {knee['max_steady_output_tok_s']} tok/s → open-loop rates {knee['rates']} req/s.", ""]
    opens = sorted((r for r in rows.values() if r.get("kind") == "open_loop"), key=lambda r: r["arrival_rate"])
    if opens:
        out += ["### Open loop (Poisson arrivals)", "", "| rate req/s | × knee | ok | err | TTFT p50 / p95 ms | ITL p50 / p95 ms | output tok/s (wall) | achieved req/s | running max | waiting max | KV max | preempt | row |",
                "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for r in opens:
            out.append(f"| {r['arrival_rate']} | {r['knee_factor']} | {r.get('requests_ok')} | {r.get('errors')} | {fmt(r.get('ttft_ms_p50'), 0)} / {fmt(r.get('ttft_ms_p95'), 0)} | "
                       f"{fmt(r.get('itl_ms_p50'))} / {fmt(r.get('itl_ms_p95'))} | {fmt(r.get('agg_output_tok_s'))} | {fmt(r.get('req_s'), 2)} | {fmt(r.get('srv_running_max'), 0)} | "
                       f"{fmt(r.get('srv_waiting_max'), 0)} | {fmt(r.get('srv_kv_usage_max'), 3)} | {fmt(r.get('srv_preemptions'), 0)} | {link(r, base)} |")
        out.append("")
    benches = [rows[k] for k in ("bench-c1", "bench-c16") if k in rows]
    if benches:
        out += ["### Cross-check: harness vs `vllm bench serve` (same server, default max-num-seqs)", "",
                "| c | tool | TTFT p50 ms | TTFT p95 ms | ITL p50 ms | TPOT p50 ms | output tok/s | source |", "|---:|---|---:|---:|---:|---:|---:|---|"]
        for b in benches:
            c = b["concurrency"]
            h = next((r for r in by_mns.get(next((m for m in by_mns if m.startswith("default")), ""), []) if r["concurrency"] == c), None)
            if h:
                out.append(f"| {c} | harness | {fmt(h.get('ttft_ms_p50'))} | {fmt(h.get('ttft_ms_p95'))} | {fmt(h.get('itl_ms_p50'))} | {fmt(h.get('tpot_ms_p50'))} | "
                           f"{fmt(h.get('steady_output_tok_s'))} (steady) / {fmt(h.get('agg_output_tok_s'))} (wall) | {link(h, base)} |")
            j = b.get("bench") or {}
            out.append(f"| {c} | vllm bench serve | {fmt(j.get('median_ttft_ms'))} | {fmt(j.get('p95_ttft_ms'))} | {fmt(j.get('median_itl_ms'))} | {fmt(j.get('median_tpot_ms'))} | "
                       f"{fmt(j.get('output_throughput'))} | {link(b, base)} |")
            if not j:
                out.append(f"| {c} | vllm bench serve | failed: rc {b.get('bench_rc')} {b.get('bench_flags_missing') or ''} {(b.get('bench_tail') or '')[-200:]} | | | | | |")
        out.append("")
    # charts
    names = sorted(by_mns)
    for metric, title, ylabel, fname in (("steady_output_tok_s", "Output throughput vs concurrency", "output tok/s (steady window)", "sweep_throughput.png"),):
        line_chart(CHARTS / fname, title, ylabel, [(f"max-num-seqs {m}", [r["concurrency"] for r in by_mns[m]],
                                                    [r.get(metric) or 0 for r in by_mns[m]], SERIES[i], "-") for i, m in enumerate(names)])
    for metric, title, fname in (("ttft_ms", "TTFT vs concurrency (p50 solid, p95 dashed)", "sweep_ttft.png"),
                                 ("itl_ms", "ITL vs concurrency (p50 solid, p95 dashed)", "sweep_itl.png")):
        s = []
        for i, m in enumerate(names):
            s.append((f"mns {m} p50", [r["concurrency"] for r in by_mns[m]], [r.get(f"{metric}_p50") or 0 for r in by_mns[m]], SERIES[i], "-"))
            s.append((f"mns {m} p95", [r["concurrency"] for r in by_mns[m]], [r.get(f"{metric}_p95") or 0 for r in by_mns[m]], SERIES[i], "--"))
        line_chart(CHARTS / fname, title, "ms", s)
    out += ["![throughput](charts/sweep_throughput.png)", "![ttft](charts/sweep_ttft.png)", "![itl](charts/sweep_itl.png)", ""]


def section_quant(rows: dict, out: list[str], base: Path, price: tuple[float, str] | None) -> None:
    if not rows:
        out += ["## Task 5 — quantization", "", "No quant rows yet.", ""]
        return
    out += ["## Task 5 — quantization: speed, quality, cost", ""]
    variants = ["fp16", "awq-int4", "gguf-q8_0", "gguf-q4_k_m"]
    out += ["| variant | engine | model | batch-1 decode tok/s (median, spread) | c=16 steady tok/s | c=16 TTFT p50 ms | PPL (wikitext-2, 40×512, 2nd half) | gsm8k | hellaswag | $/1M out tok @ c=16 | rows |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    dec_vals, names = [], []
    for v in variants:
        d, c, p, l = (rows.get(f"{v}-{x}") for x in ("decode", "c16", "ppl", "lmeval"))
        fail = rows.get(f"{v}-server") or rows.get(f"{v}-skipped")
        any_r = d or c or p or l or fail
        if not any_r:
            continue
        lm = (l or {}).get("lmeval") or {}
        def task(t):
            m = lm.get(t) or {}
            keys = [k for k in m if not k.endswith("_stderr") and "stderr" not in k and isinstance(m[k], (int, float))]
            pick = next((k for k in keys if k.startswith("exact_match,strict")), None) or next((k for k in keys if k.startswith("acc_norm")), None) or (keys[0] if keys else None)
            if not pick:
                return f"failed (rc {(l or {}).get('lmeval_rc')})" if l else "—"
            se = m.get(pick.replace(",", "_stderr,", 1))
            return f"{m[pick]:.3f} ± {se:.3f} (`{pick}`)" if isinstance(se, (int, float)) else f"{m[pick]:.3f} (`{pick}`)"
        ppl = (p or {}).get("ppl")
        tok16 = (c or {}).get("steady_output_tok_s")
        cost = f"{price[0] / (tok16 * 3600) * 1e6:.3f}" if price and tok16 else "—"
        if d and d.get("decode_tok_s_median"):
            dec_vals.append(d["decode_tok_s_median"]); names.append(v)
        out.append(f"| {v} | {any_r.get('engine', '—')} | `{any_r.get('model')}` | "
                   f"{fmt((d or {}).get('decode_tok_s_median'), 2)} ({fmt((d or {}).get('decode_spread_pct'), 1)} %) | {fmt(tok16)} | {fmt((c or {}).get('ttft_ms_p50'), 0)} | "
                   f"{fmt(ppl, 3) if ppl else ((p or {}).get('ppl_error') or '—')[:80]} | {task('gsm8k')} | {task('hellaswag')} | {cost} | "
                   f"{link(any_r, base)}{' — ' + str(fail.get('reason') or '; '.join(fail.get('error_lines', [])[-1:]))[:200] if fail else ''} |")
    out.append("")
    l0 = next((r for r in rows.values() if r.get("kind") == "lmeval"), None)
    if l0:
        out += [f"lm-eval {l0.get('lmeval_version')} `local-completions`, --limit {l0.get('lmeval_limit')} (first N docs), command in the row (`lmeval_cmd`).", ""]
    if price:
        out += [f"Cost: {price[1]}. Formula `$ / 1M = $/h ÷ (tok/s × 3600) × 1e6` (benchmarks/cost.py).", ""]
    if dec_vals:
        bar_chart(CHARTS / "quant_decode.png", "Batch-1 decode by quantization (one T4)", "tok/s (median of 5)", names, dec_vals)
        out += ["![decode](charts/quant_decode.png)", ""]


def section_runs(out: list[str]) -> None:
    f = T4 / "runs.jsonl"
    if not f.exists():
        return
    runs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    tot = sum(r.get("gpu_hours_script") or 0 for r in runs)
    ub = sum(r.get("gpu_hours_upper_bound") or 0 for r in runs)
    out += ["## Kaggle runs (GPU time)", "", "| run | stage | status | script session s | GPU-h (script) | GPU-h (push→done, upper bound) |", "|---|---|---|---:|---:|---:|"]
    for r in runs:
        out.append(f"| {r['run_id']} | {r['stage']} | {r['status']} | {fmt(r.get('script_session_s'))} | {fmt(r.get('gpu_hours_script'), 3)} | {fmt(r.get('gpu_hours_upper_bound'), 3)} |")
    out += [f"| **total** | | | | **{tot:.3f}** | **{ub:.3f}** |", ""]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--price-json", type=Path, help="saved Azure price response (benchmarks/cost.py --azure-price-json)")
    a = ap.parse_args()
    CHARTS.mkdir(parents=True, exist_ok=True)
    price = None
    if a.price_json:
        sys.path.insert(0, str(REPO / "benchmarks"))
        from cost import azure_price
        price = azure_price(a.price_json)
    out = ["# T4 engine results — summary", "", "Generated by `benchmarks/analyze.py` from the stage JSONL files; do not edit by hand. "
           "Every row links its JSONL. Narrative and caveats: [README.md](README.md).", ""]
    facts = section_baseline(load("baseline"), out, T4)
    section_predictions(facts, out)
    kv = load("kvgrid")
    out += ["## Task 2 — KV capacity (8B AWQ INT4)", "", "Full table: [benchmarks/kv_capacity_table.md](../../kv_capacity_table.md).", ""]
    (REPO / "benchmarks" / "kv_capacity_table.md").write_text("\n".join(section_kv(kv, REPO / "benchmarks")) + "\n")
    section_sweep(load("sweep"), out, T4)
    section_quant(load("quant"), out, T4, price)
    section_runs(out)
    (T4 / "summary.md").write_text("\n".join(out) + "\n")
    print(f"wrote {T4 / 'summary.md'}, {REPO / 'benchmarks' / 'kv_capacity_table.md'}, charts in {CHARTS}")


if __name__ == "__main__":
    main()
