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


def load(stage: str, model: str | None = None) -> dict[str, dict]:
    """Rows of a stage merged by key (a later run overrides an earlier one), optionally for one model:
    baseline and sweep keys repeat per model (Qwen substitute first, then Llama), so they are grouped."""
    rows: dict[str, dict] = {}
    for f in sorted(T4.glob(f"*_{stage}/results/{stage}/{stage}.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if model is not None and r.get("model") != model:
                    continue
                r["_src"] = str(f.relative_to(REPO))
                rows[r["key"]] = r
    return rows


def models(stage: str) -> list[str]:
    """Models a stage measured, the prediction target (Llama) first."""
    seen = {r["model"] for r in load(stage).values() if r.get("model")}
    seen |= {json.loads(l).get("model") for f in T4.glob(f"*_{stage}/results/{stage}/{stage}.jsonl")
             for l in f.read_text().splitlines() if l.strip()} - {None}
    return sorted(seen, key=lambda m: (not m.startswith("meta-llama/"), m))


def slug(model: str) -> str:
    return model.split("/")[-1].lower()


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


def line_chart(path: Path, title: str, ylabel: str, series: list[tuple[str, list, list, str, str]], logx=True, logy=False,
               xlabel: str = "concurrent clients (closed loop)", xticks: bool = True) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 4), facecolor=SURFACE)
    for name, xs, ys, color, ls in series:
        ax.plot(xs, ys, color=color, linestyle=ls, linewidth=2, marker="o", markersize=5, label=name)
        if xs and len(series) <= 2:   # p50/p95 pairs end on top of each other: legend only
            ax.annotate(name, (xs[-1], ys[-1]), textcoords="offset points", xytext=(6, 0), color=INK, fontsize=8, va="center")
    if logx:
        ax.set_xscale("log", base=2)
        if xticks:
            xs_all = sorted({x for s in series for x in s[1]})
            ax.set_xticks(xs_all, [str(x) for x in xs_all])
    if logy:
        ax.set_yscale("log")
    style(ax, title, xlabel, ylabel)
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
    model = next((r["model"] for r in rows.values() if r.get("model")), "?")
    out += [f"## Task 1 — baseline serve: `{model}`", ""]
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
    out += [f"## Predictions vs measured: `{f.get('model')}`" + ("" if llama else " (substitute)"), "",
            f"Measured model: `{f.get('model')}`." + ("" if llama else " The predictions were made for Llama-3.2-3B; the KV rows are restated for this model from its config.json (formula above)."), "",
            "| quantity | predicted | measured | why different |", "|---|---|---|---|",
            f"| batch-1 decode tok/s | ≤ {PRED['decode_tok_s_max']} (expect {PRED['decode_tok_s_expect']}) | {fmt(f.get('decode_median'), 2)} baseline session (spread {fmt(f.get('decode_spread'), 1)} %)"
            + (f"; {fmt(f['decode_quant'], 2)} quant session (spread {fmt(f.get('decode_quant_spread'), 1)} %)" if f.get("decode_quant") else "")
            + (f" | within the ≤ {PRED['decode_tok_s_max']} ceiling; {(f['decode_median'] / 35 - 1) * 100:+.1f} % vs the top of the expected 30–35 |"
               if llama and f.get("decode_median") else " | sessions differ in GPU clock (SW power capping), README |"),
            f"| KV bytes/token | {PRED['kv_bytes_per_token_llama32_3b']:,} (Llama-3.2-3B) | {fmt(b)} (config.json) | {'same model' if llama else 'different model (Qwen2.5-3B: 2 KV heads, GQA, per its config.json)'} |",
            f"| KV pool tokens @ 0.90 | ≈ {PRED['kv_tokens']:,}" + (f" → {carried:,} restated (same KV bytes, this model's B/token)" if carried else "") +
            f" | {fmt(f.get('gpu_kv_cache_tokens'))} (log) | "
            + (f"{(f['gpu_kv_cache_tokens'] / (PRED['kv_tokens'] if llama else carried) - 1) * 100:+.1f} % vs prediction"
               if f.get("gpu_kv_cache_tokens") and (llama or carried) else "—")
            + (f"; available KV {fmt(f.get('available_kv_gib'), 2)} GiB ÷ {fmt(b)} B = {fmt(f.get('kv_tokens_from_mem'))} tokens" if f.get("kv_tokens_from_mem") else "") + " |",
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
    cfgf = REPO / Path(r0["_src"]).parent / "logs" / "model-config.json"
    if cfgf.exists():
        b, formula = kv_bytes_per_token(json.loads(cfgf.read_text()))
        out += ["", f"KV bytes/token from the model's `config.json`: {formula}. Check (computed): "
                + "; ".join(f"{r['available_kv_gib']} GiB / {b:,} B = {int(r['available_kv_gib'] * 2**30 / b):,} tokens vs {fmt(r.get('kv_tokens'))} reported"
                            for r in cells if r.get("max_model_len") == cells[0]["max_model_len"] and r.get("available_kv_gib")) + "."]
    out += ["", "Reading: the KV pool is set by `--gpu-memory-utilization` alone (memory left after weights, activations and "
            "CUDA graphs); `--max-model-len` only changes how many full-length sequences fit in it."]
    return out + [""]


def section_sweep(rows: dict, out: list[str], base: Path) -> None:
    closed = [r for r in rows.values() if r.get("kind") == "closed_loop"]
    if not closed:
        out += ["## Task 4 — concurrency sweep", "", "No sweep rows yet.", ""]
        return
    r0 = closed[0]
    tag = slug(r0["model"])
    out += [f"## Task 4 — concurrency sweep: `{r0['model']}`", "",
            f"Model `{r0['model']}` @ `{r0.get('model_revision')}` ({r0.get('model_choice')}) · vLLM {r0.get('vllm_version')} · prefix caching: {r0.get('prefix_caching')}.",
            f"Client: benchmarks/harness, `/v1/completions` streamed, {r0['client']['prompt_tokens']} prompt tokens (unique random words, uuid prefix), "
            f"max_tokens {r0['client']['max_tokens']} ± {int(r0['client']['max_tokens_jitter'] * 100)} %, ignore_eos, start jitter {r0['client']['start_jitter_s']} s, "
            f"requests max(20, 4×c), 2 warmup. TTFT/ITL client-side (first token chunk / chunk gaps); srv_* = vLLM /metrics sampled at 1 Hz; gpu_* = NVML at 1 Hz.", "",
            "| max-num-seqs | c | ok | err | TTFT p50 / p95 ms | ITL p50 / p95 ms | steady out tok/s | req/s | running max | waiting max | KV usage max | preempt | GPU util mean % | power mean W | row |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    by_mns: dict[str, list[dict]] = {}
    for r in sorted(closed, key=lambda r: (str(r["max_num_seqs"]), r["concurrency"])):
        by_mns.setdefault(str(r["max_num_seqs"]).replace(" (None)", ""), []).append(r)
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
        out += ["### Cross-check: harness vs `vllm bench serve`", "",
                "Both in the **same Kaggle session, back to back**, same server (default max-num-seqs), same workload: "
                "256 random prompt tokens, 128 output tokens, ignore_eos, no jitter, max(20, 4×c) requests. "
                "Both clocks start just before the HTTP POST and stop at the first SSE chunk carrying `choices` "
                "(harness: benchmarks/harness/client.py `one_request`; bench: vLLM 0.31.0 `vllm/benchmarks/lib/endpoint_request_func.py` "
                "`async_request_openai_completions`, lines 202–240). Server-side `vllm:time_to_first_token_seconds` mean shown for the harness run.", "",
                "| c | tool | TTFT p50 ms | TTFT p95 ms | ITL p50 ms | TPOT p50 ms | output tok/s | SM clock mean MHz | srv TTFT mean ms | row |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for b in benches:
            c = b["concurrency"]
            h = rows.get(f"harness-matched-c{c}")
            same = h is not None and h.get("run_id") == b.get("run_id")
            if h:
                out.append(f"| {c} | harness{'' if same else ' (DIFFERENT session)'} | {fmt(h.get('ttft_ms_p50'))} | {fmt(h.get('ttft_ms_p95'))} | {fmt(h.get('itl_ms_p50'))} | "
                           f"{fmt(h.get('tpot_ms_p50'))} | {fmt(h.get('agg_output_tok_s'))} (wall) | {fmt(h.get('gpu_sm_clock_mhz_mean'), 0)} | {fmt(h.get('m_srv_ttft_ms_mean'))} | {link(h, base)} |")
            j = b.get("bench") or {}
            if j:
                out.append(f"| {c} | vllm bench serve | {fmt(j.get('median_ttft_ms'))} | {fmt(j.get('p95_ttft_ms'))} | {fmt(j.get('median_itl_ms'))} | {fmt(j.get('median_tpot_ms'))} | "
                           f"{fmt(j.get('output_throughput'))} | {fmt(b.get('gpu_sm_clock_mhz_mean'), 0)} | — | {link(b, base)} |")
            else:
                out.append(f"| {c} | vllm bench serve | failed: rc {b.get('bench_rc')} {b.get('bench_flags_missing') or ''} | | | | | | | {link(b, base)} |")
        out.append("")
    diags = [rows[k] for k in ("benchdiag-A", "benchdiag-B", "benchdiag-C", "benchdiag-D") if k in rows]
    if diags:
        out += ["### c=16 TTFT-tail diagnosis (`vllm bench serve`)", "",
                "A then B on one server (A on a cold server, B warm); C and D each on a fresh server.", "",
                "| run | extra flags | TTFT p50 / p95 ms | first 16 requests TTFT s (min–max) | later requests TTFT s (max) | TPOT p50 ms | output tok/s | row |",
                "|---|---|---:|---:|---:|---:|---:|---|"]
        for d in diags:
            j, t = d.get("bench") or {}, d.get("bench_ttfts_s") or []
            first, rest = t[:16], t[16:]
            out.append(f"| {d['key']} | `{' '.join(d.get('extra', []))}` | {fmt(j.get('median_ttft_ms'))} / {fmt(j.get('p95_ttft_ms'))} | "
                       f"{fmt(min(first), 2) if first else '—'}–{fmt(max(first), 2) if first else '—'} | {fmt(max(rest), 2) if rest else '—'} | "
                       f"{fmt(j.get('median_tpot_ms'))} | {fmt(j.get('output_throughput'))} | {link(d, base)} |")
        out.append("")
    # charts
    names = sorted(by_mns)
    for metric, title, ylabel, fname in (("steady_output_tok_s", f"Output throughput vs concurrency — {tag}", "output tok/s (steady window)", f"sweep_throughput-{tag}.png"),):
        line_chart(CHARTS / fname, title, ylabel, [(f"max-num-seqs {m}", [r["concurrency"] for r in by_mns[m]],
                                                    [r.get(metric) or 0 for r in by_mns[m]], SERIES[i], "-") for i, m in enumerate(names)])
    for metric, title, fname in (("ttft_ms", f"TTFT vs concurrency, p50 solid / p95 dashed — {tag}", f"sweep_ttft-{tag}.png"),
                                 ("itl_ms", f"ITL vs concurrency, p50 solid / p95 dashed — {tag}", f"sweep_itl-{tag}.png")):
        s = []
        for i, m in enumerate(names):
            s.append((f"mns {m} p50", [r["concurrency"] for r in by_mns[m]], [r.get(f"{metric}_p50") or 0 for r in by_mns[m]], SERIES[i], "-"))
            s.append((f"mns {m} p95", [r["concurrency"] for r in by_mns[m]], [r.get(f"{metric}_p95") or 0 for r in by_mns[m]], SERIES[i], "--"))
        line_chart(CHARTS / fname, title, "ms (log scale)", s, logy=True)
    out += [f"![throughput](charts/sweep_throughput-{tag}.png)", f"![ttft](charts/sweep_ttft-{tag}.png)", f"![itl](charts/sweep_itl-{tag}.png)", ""]


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
            keys = [k for k in m if "stderr" not in k and isinstance(m[k], (int, float)) and k not in ("sample_len",)
                    and (k.startswith("exact_match") or k.startswith("acc"))]
            if not keys:
                return f"failed (rc {(l or {}).get('lmeval_rc')})" if l else "—"
            parts = []
            for k in sorted(keys):
                se = m.get(k.replace(",", "_stderr,", 1))
                parts.append(f"{k.split(',')[0] if t == 'hellaswag' else k.split(',')[1]} {m[k]:.3f}" + (f" ± {se:.3f}" if isinstance(se, (int, float)) else ""))
            return "<br>".join(parts)
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


NCCL_LABEL = ("2 × Tesla T4 in one Kaggle VM, GPU↔GPU over PCIe — GPU collective communication inside one box; "
              "not the scale-out fabric, not NVLink")
GIB = 2**30


def nccl_run(marker: str = "allreduce-default-r1") -> tuple[str, dict[str, dict]] | None:
    """Rows of the latest nccl run with data under `marker` (the sweep, or "p2pcheck-default" for the P2P
    follow-up). All rows come from one session; runs are never merged."""
    for f in sorted(T4.glob("*_nccl/results/nccl/nccl.jsonl"), reverse=True):
        rows = {(r := json.loads(l))["key"]: r | {"_src": str(f.relative_to(REPO))}
                for l in f.read_text().splitlines() if l.strip()}
        if rows.get(marker, {}).get("points"):
            return str(f.relative_to(REPO)), rows
    return None


def nccl_table(rows: dict[str, dict]) -> list[str]:
    out = ["| run | env | rc | busbw @ 1 GiB (GB/s) | algbw @ 1 GiB | time @ 8 B (µs) | avg busbw | #wrong | transport | algo/proto @ 8 B → 1 GiB |",
           "|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for k, r in rows.items():
        if not r.get("binary"):
            continue
        env = " ".join(f"{a}={b}" for a, b in (r.get("env_extra") or {}).items()) or "default"
        coll = next(iter(r.get("algo_by_size") or {}), None)
        ab = (r.get("algo_by_size") or {}).get(coll, {})
        algo = f"{ab.get('8', '?')} → {ab.get(str(GIB), '?')}" if ab else "—"
        out.append(f"| `{k}` | {env} | {r.get('rc')} | {fmt(nccl_at(r, GIB), 2)} | {fmt(nccl_at(r, GIB, 'algbw_gbs'), 2)} | "
                   f"{fmt(nccl_at(r, 8, 'time_us'), 1)} | {fmt(r.get('avg_busbw_gbs'), 2)} | {r.get('wrong_total')} | "
                   f"{', '.join(r.get('transports') or []) or '—'} | {algo} |")
    return out


def nccl_at(r: dict, size: int, field: str = "busbw_gbs", half: str = "oop"):
    return next((p[half][field] for p in r.get("points", []) if p["size_b"] == size), None)


def nccl_facts(rows: dict) -> dict:
    """Headline numbers and the session caveat for one nccl run."""
    reps = [r for k, r in sorted(rows.items()) if k.startswith("allreduce-default-r") and r.get("points")]
    bus = [nccl_at(r, GIB) for r in reps]
    small = [nccl_at(r, 8, "time_us") for r in reps]
    p2p_off = nccl_at(rows.get("allreduce-p2p-disabled", {}), GIB)
    sock = nccl_at(rows.get("allreduce-p2p-shm-disabled", {}), GIB)
    med = sorted(bus)[len(bus) // 2] if bus and None not in bus else None
    spread = (max(bus) - min(bus)) / med * 100 if med else None
    wrong = sum(r.get("wrong_total") or 0 for r in rows.values())
    notes = []
    if spread is not None and spread > 10:
        notes.append(f"unstable session: 1 GiB busbw spread {spread:.1f} % over {len(bus)} repeats")
    if wrong:
        notes.append(f"correctness check: {wrong} wrong values")
    return {"reps": reps, "bus_1g": bus, "bus_1g_med": med, "spread_pct": spread, "small_8b_us": small,
            "p2p_off_1g": p2p_off, "sock_1g": sock, "wrong": wrong, "note": "; ".join(notes)}


def section_nccl(out: list[str], base: Path) -> None:
    got = nccl_run()
    if not got:
        out += ["## NCCL — 2 × T4 collectives (PCIe, one box)", "", "No full nccl run yet.", ""]
        return
    src, rows = got
    pr, bd = rows.get("probe", {}), rows.get("build", {})
    f = nccl_facts(rows)
    r1 = f["reps"][0]
    pcie = (r1.get("pcie_during") or [{}])[0]
    t = pr.get("torch") or {}
    out += ["## NCCL — 2 × T4 collectives (PCIe, one box)", "", f"**{NCCL_LABEL}.** nccl-tests rows from one session: "
            f"[{Path(src).parts[3]}]({Path(*(['..'] * len(base.relative_to(REPO).parts))) / src}).", "",
            f"- Topology: `nvidia-smi topo -m` GPU0↔GPU1 = **{pr.get('topo_gpu0_gpu1')}**; `topo -p2p r` = "
            f"**{pr.get('smi_p2p_read_gpu0_gpu1')}**; torch `can_device_access_peer(0,1)` = **{t.get('p2p_0_1')}**; "
            f"PCIe under load Gen{pcie.get('pcie.link.gen.current')} x{pcie.get('pcie.link.width.current')} "
            f"(idle Gen{(pr.get('pcie_idle') or [{}])[0].get('pcie.link.gen.current')}).",
            f"- Versions: NCCL **{r1.get('nccl_version_log')}** (`{bd.get('nccl_wheel')}`, library code "
            f"{r1.get('nccl_library_code')} printed by nccl-tests); nccl-tests {bd.get('nccl_tests_tag')} "
            f"(`{(bd.get('nccl_tests_commit') or '')[:12]}`), nvcc {bd.get('nvcc')}, driver {r1.get('driver')} "
            f"(CUDA {r1.get('cuda_driver')}), torch {t.get('torch')} (its NCCL {t.get('nccl')}).",
            f"- Transport NCCL chose (default run): **{', '.join(r1.get('transports') or [])}**; graph "
            f"`{(r1.get('graph_pattern') or [''])[0]}`; {', '.join(map(str, r1.get('coll_channels') or []))} coll channels.", ""]
    out += nccl_table(rows)
    if (pc := nccl_run("p2pcheck-default")):
        psrc, prow = pc
        pp = prow.get("probe", {})
        out += ["", f"P2P follow-up, one session ([{Path(psrc).parts[3]}]({Path(*(['..'] * len(base.relative_to(REPO).parts))) / psrc})): "
                f"`topo -p2p r` = {pp.get('smi_p2p_read_gpu0_gpu1')}, torch P2P = {(pp.get('torch') or {}).get('p2p_0_1')}. "
                "NCCL 2.28.9 uses P2P only up to PXB by default; `NCCL_P2P_LEVEL=PHB` allows it on this PHB path.", ""]
        out += nccl_table(prow)
    out += ["", "busbw = algbw × 2(N−1)/N for all-reduce, (N−1)/N for all-gather / reduce-scatter / all-to-all, 1 for "
            "send/recv (nccl-tests PERFORMANCE.md); at N = 2 all-reduce busbw = algbw. Out-of-place columns. "
            "Model check against fabric/design/collectives.py: [fabric/design/nccl_check.md](../../../fabric/design/nccl_check.md).", ""]
    series = []
    for (k, name), color in zip((("allreduce-default-r1", "default (r1)"), ("allreduce-ring", "NCCL_ALGO=Ring"),
                                 ("allreduce-tree", "NCCL_ALGO=Tree"), ("allreduce-p2p-shm-disabled", "P2P+SHM disabled (Socket)")), SERIES):
        if (r := rows.get(k)) and r.get("points"):
            series.append((name, [p["size_b"] for p in r["points"]], [p["oop"]["busbw_gbs"] for p in r["points"]], color, "-"))
    if series:
        line_chart(CHARTS / "nccl-allreduce-busbw.png", "2×T4 all-reduce bus bandwidth (PCIe, one box)", "busbw (GB/s)",
                   series, xlabel="message size (bytes)", xticks=False)
        out += ["![all-reduce busbw](charts/nccl-allreduce-busbw.png)", ""]


# ---------------------------------------------------------------- P8 on 2 x T4 (stage p8x2)

P8_LABEL = "Kaggle 2×T4, real engines; routing not exercised"
P8_COND = {"idle": "idle, no background", "main": "main: L 2×3K / S 3×200 prompts, 64 out, vLLM defaults",
            "longout": "long-output: as main, 512 out", "mns2": "mns2: as main, both servers --max-num-seqs 2 (P8 sim slots, not default)"}
P8_STYLE = {"L": (SERIES[0], "o", "L (long prompts, GPU 0)"), "S": (SERIES[1], "s", "S (short prompts, GPU 1)")}


def p8x2_run() -> tuple[Path, dict[str, dict]] | None:
    """Latest p8x2 run with at least one measured condition: (results dir, rows by key)."""
    for f in sorted(T4.glob("*_p8x2/results/p8x2/p8x2.jsonl"), reverse=True):
        rows = {}
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r["_src"] = str(f.relative_to(REPO))
                rows[r["key"]] = r
        if any(r.get("kind") == "condition_window" for r in rows.values()):
            return f.parent, rows
    return None


def p8x2_analysis(d: Path) -> dict:
    sys.path.insert(0, str(REPO / "scripts"))
    import probe_p8_t4x2 as p8
    return p8.analyze(d)


def p8x2_charts(d: Path, res: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker
    sys.path.insert(0, str(REPO / "scripts"))
    import probe_p8_t4x2 as p8
    probes = p8.read_jsonl(d / "probes.jsonl")
    samples = [s for s in p8.read_jsonl(d / "metrics_1hz.jsonl") if "error" not in s]
    conds = [c["condition"] for c in res["conditions"]]
    made = []
    # 1. TTFT per probe, L vs S, per condition
    fig, ax = plt.subplots(figsize=(7.5, 4), facecolor=SURFACE)
    for xi, cond in enumerate(conds):
        for s, off in (("L", -0.16), ("S", 0.16)):
            v = [p["ttft_s"] for p in probes if p["condition"] == cond and p["server"] == s and p.get("ttft_s") is not None]
            if not v:
                continue
            col, mk, name = P8_STYLE[s]
            ax.scatter([xi + off + (i % 5 - 2) * 0.025 for i in range(len(v))], v, s=22, color=col, marker=mk,
                       edgecolor=SURFACE, linewidth=0.8, label=name if xi == 0 else None, zorder=3)
            med = sorted(v)[len(v) // 2] if len(v) % 2 else sum(sorted(v)[len(v) // 2 - 1:len(v) // 2 + 1]) / 2
            ax.hlines(med, xi + off - 0.1, xi + off + 0.1, color=INK, linewidth=2, zorder=4)
    ax.set_ylim(bottom=0)
    ax.set_xticks(range(len(conds)), conds)
    style(ax, "Probe TTFT on L vs S per condition (bar = median)", f"condition — {P8_LABEL}", "TTFT (s)")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    fig.savefig(CHARTS / "p8x2_ttft.png", dpi=130)
    plt.close(fig)
    made.append("p8x2_ttft.png")
    # 2. probe inter-token gaps, ECDF per server, one panel per L/S condition
    lc = [c for c in conds if any(p["condition"] == c and p["server"] == "S" for p in probes)]
    fig, axes = plt.subplots(1, len(lc), figsize=(3.2 * len(lc), 3.6), facecolor=SURFACE, sharey=True, squeeze=False)
    for ax, cond in zip(axes[0], lc):
        for s in ("L", "S"):
            g = sorted(x * 1000 for p in probes if p["condition"] == cond and p["server"] == s for x in p.get("itl_s", []))
            if g:
                col, mk, name = P8_STYLE[s]
                ax.plot(g, [(i + 1) / len(g) for i in range(len(g))], color=col, linewidth=2,
                        linestyle="-" if s == "L" else "--", label=name)
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(matplotlib.ticker.LogLocator(base=10, subs=(1.0, 3.0)))
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        style(ax, cond, "probe inter-token gap (ms, log)", "fraction of gaps ≤ x" if ax is axes[0][0] else "")
    axes[0][0].legend(frameon=False, fontsize=7, labelcolor=INK, loc="lower right")
    fig.suptitle(f"Probe ITL per server — {P8_LABEL}", x=0.01, ha="left", fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(CHARTS / "p8x2_itl.png", dpi=130)
    plt.close(fig)
    made.append("p8x2_itl.png")
    # 3. running requests and KV usage over the whole run, both servers (two panels, one scale each)
    if samples:
        t0 = min(s["t"] for s in samples)
        fig, axes = plt.subplots(2, 1, figsize=(8, 5), facecolor=SURFACE, sharex=True)
        for ax, key, lab in ((axes[0], "running", "running requests"), (axes[1], "kv", "KV cache usage (0–1)")):
            for s in ("L", "S"):
                pts = [(x["t"] - t0, x[key]) for x in samples if x["server"] == s and key in x and x["condition"] != "setup"]
                col, mk, name = P8_STYLE[s]
                ax.plot([p[0] / 60 for p in pts], [p[1] for p in pts], color=col, linewidth=1.5,
                        linestyle="-" if s == "L" else "--", label=name)
            for c in res["conditions"]:
                w = next((r for r in p8.read_jsonl(d / "p8x2.jsonl") if r.get("key") == f"cond-{c['condition']}"), None)
                if w:
                    ax.axvline((w["t_start"] - t0) / 60, color=AXIS, linewidth=0.8)
                    if key == "running":
                        ax.annotate(c["condition"], ((w["t_start"] - t0) / 60, 1), xycoords=("data", "axes fraction"),
                                    xytext=(3, -10), textcoords="offset points", fontsize=7, color=MUTED)
            style(ax, "" if key == "kv" else "Engine gauges, 1 Hz, both servers",
                  f"minutes since first sample — {P8_LABEL}" if key == "kv" else "", lab)
        axes[0].legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower left", bbox_to_anchor=(0.0, 1.08), ncol=2)
        fig.tight_layout()
        fig.savefig(CHARTS / "p8x2_gauges.png", dpi=130)
        plt.close(fig)
        made.append("p8x2_gauges.png")
    return made


def section_p8x2(out: list[str], base: Path) -> dict | None:
    got = p8x2_run()
    if not got:
        return None
    d, rows = got
    res = p8x2_analysis(d)
    run_id = d.parts[-3]
    src = Path(next(iter(rows.values()))["_src"])
    rel = lambda p: Path(*([".."] * len(base.relative_to(REPO).parts))) / p
    eng = rows.get("engine-config", {})
    st = {n: rows.get(f"startup-{n}", {}) for n in ("L", "S")}
    out += ["## P8 on 2 × T4 — size-blind routing (real engines)", "",
            f"**{P8_LABEL}.** Run {run_id}, raw [{src.name}]({rel(src)}), probes [probes.jsonl]({rel(src.parent / 'probes.jsonl')}). "
            f"Narrative and prediction: [p8_t4x2.md](p8_t4x2.md).", "",
            f"Engine: vLLM {next(iter(rows.values())).get('vllm_version')}, chunked prefill "
            f"{eng.get('chunked_prefill_enabled', eng.get('enable_chunked_prefill'))}, max_num_batched_tokens "
            f"{eng.get('max_num_batched_tokens')}, max_num_seqs {eng.get('max_num_seqs')} (row `engine-config`); "
            f"KV pool L/S {fmt(st['L'].get('gpu_kv_cache_tokens'))} / {fmt(st['S'].get('gpu_kv_cache_tokens'))} tokens (startup log).", "",
            "| condition | server | probes ok | TTFT p50 / p95 / max (s) | ITL p50 / p95 (ms) | e2e p50 (s) | bg out tok/s (client) | prompt tok/s (server) | running / waiting / KV mean | SM clock mean (MHz) | GPU util mean |",
            "|---|---|---:|---|---|---:|---:|---:|---|---:|---:|"]
    for c in res["conditions"]:
        for s, r in c["servers"].items():
            if not r["probes"] and not r["bg_requests_done"]:
                continue
            t, i, g = r["ttft_s"], r["itl_s"], r.get("gpu", {})
            out.append(f"| {c['condition']} | {s} | {r['probes_ok']}/{r['probes']} | "
                       f"{fmt(t.get('p50'), 3)} / {fmt(t.get('p95'), 3)} / {fmt(t.get('max'), 3)} | "
                       f"{fmt(i['p50'] * 1000 if i.get('p50') is not None else None)} / {fmt(i['p95'] * 1000 if i.get('p95') is not None else None)} | "
                       f"{fmt(r['e2e_s'].get('p50'), 2)} | {fmt(r['bg_output_tok_s_client'])} | {fmt(r['srv_prompt_tok_s'])} | "
                       f"{fmt(r.get('gauge_running_mean'), 2)} / {fmt(r.get('gauge_waiting_mean'), 2)} / {fmt(r.get('gauge_kv_mean'), 4)} | "
                       f"{fmt(g.get('sm_clock_mhz_mean'))} | {fmt(g.get('util_gpu_pct_mean'))} |")
    out += ["", "| condition | median TTFT L (s) | median TTFT S (s) | gap L − S (s) | 95 % bootstrap CI of gap (s) | ratio | n L / S | median e2e L / S (s) | L prefilling (share of window) | L probes sent during an L prefill |",
            "|---|---:|---:|---:|---|---:|---|---|---:|---|"]
    for c in res["conditions"]:
        h = c.get("headline")
        if h:
            ci = h["gap_ci95_bootstrap_s"]
            out.append(f"| {c['condition']} | {h['median_ttft_L_s']:.3f} | {h['median_ttft_S_s']:.3f} | **{h['gap_s']:.3f}** | "
                       f"{f'{ci[0]:.3f} … {ci[1]:.3f}' if ci else '—'} | {h['ratio']} | {h['n_L']} / {h['n_S']} | "
                       f"{h['median_e2e_L_s']:.2f} / {h['median_e2e_S_s']:.2f} | {fmt(h['phase_L']['prefill_share_of_window'], 3)} | "
                       f"{h['phase_L']['probes_sent_in_prefill']} / {h['phase_L']['probes']} |")
    out += ["", "**What a router would have seen** — computed offline from real engine metrics (pre-send /metrics of both servers "
            "per probe; formulas from llm-d-router v0.9.0, see [p8_t4x2.md](p8_t4x2.md#what-a-router-would-have-seen)). "
            "Stock = queue ×2 + kv-cache ×2 + prefix ×3, max-score-picker; token-load = stock + token-load ×4, threshold 8192, "
            "token load rebuilt from the background log (bytes/4 estimate, released at first chunk).", "",
            "| condition | n | L running / waiting / KV (mean) | S running / waiting / KV (mean) | stock picks L / S / tie | stock margin (median) | token-load picks L / S / tie |",
            "|---|---:|---|---|---|---:|---|"]
    for rt in res["router"]:
        if not rt["n"]:
            continue
        m = {s: {k: sum(r["snap"][s][k] for r in rt["rows"]) / rt["n"] for k in ("running", "waiting", "kv")} for s in ("L", "S")}
        sp, tp = rt["stock_picks"], rt["token_picks"]
        out.append(f"| {rt['condition']} | {rt['n']} | {m['L']['running']:.2f} / {m['L']['waiting']:.2f} / {m['L']['kv']:.4f} | "
                   f"{m['S']['running']:.2f} / {m['S']['waiting']:.2f} / {m['S']['kv']:.4f} | {sp['L']} / {sp['S']} / {sp['tie']} | "
                   f"{rt['stock_margin_median']:.4f} | {tp['L']} / {tp['S']} / {tp['tie']} |")
    charts = p8x2_charts(d, res)
    out += [""] + [f"![{c}](charts/{c})" for c in charts] + [""]
    return {"dir": d, "rows": rows, "res": res}


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


def caveat(r: dict) -> str:
    """Flag rows from an unstable or clock-limited Kaggle session, so they are not quoted as the T4's speed."""
    notes = []
    if (sp := r.get("decode_spread_pct")) is not None and float(sp) > 20:
        notes.append(f"unstable session: decode spread {sp} % (power capping suspected)")
    if r.get("_session_note"):
        notes.append(r["_session_note"])
    return "**" + "; ".join(notes) + "**" if notes else ""


def headlines(price: tuple[float, str] | None) -> list[str]:
    """One row per headline number for RESULTS.md, each linked to the JSONL row it came from."""
    rows: list[tuple[str, str, str, dict]] = []
    for bm in models("baseline"):
        b = load("baseline", bm)
        if (r := b.get("decode-batch1")) and r.get("decode_tok_s_median"):
            rows.append(("batch-1 decode", f"{r['decode_tok_s_median']:.2f} tok/s (spread {r['decode_spread_pct']} %, n={r['decode_n']})", r["model"], r))
        if (r := b.get("startup")):
            if r.get("gpu_kv_cache_tokens"):
                rows.append(("KV pool @ --gpu-memory-utilization 0.90, max-model-len 4096", f"{r['gpu_kv_cache_tokens']:,} tokens (log)", r["model"], r))
            if r.get("blocks_x_block_size"):
                rows.append(("GPU blocks × block size", f"{r['num_gpu_blocks']:,} × {r['block_size']} = {r['blocks_x_block_size']:,} tokens", r["model"], r))
            if r.get("model_weights_gib"):
                rows.append(("model weight memory", f"{r['model_weights_gib']} GiB (log)", r["model"], r))
    kv = [r for r in load("kvgrid").values() if r.get("kind") == "kv_cell"]
    if kv:
        ok = [r for r in kv if r.get("started")]
        rows.append(("8B AWQ grid cells that started", f"{len(ok)} / {len(kv)}", kv[0]["model"], kv[0]))
        if ok:
            best = max(ok, key=lambda r: r.get("kv_tokens") or 0)
            rows.append(("8B AWQ largest KV pool", f"{best.get('kv_tokens'):,} tokens @ util {best['gpu_memory_utilization']}, len {best['max_model_len']}", best["model"], best))
    # Best stable batch-1 decode per model (spread <= 20 %), used to spot clock-limited sweep sessions.
    best_b1: dict[str, float] = {}
    for stage, key in (("baseline", "decode-batch1"), ("quant", "fp16-decode")):
        for mm in models(stage):
            r = load(stage, mm).get(key) or {}
            if r.get("decode_tok_s_median") and float(r.get("decode_spread_pct") or 0) <= 20:
                best_b1[r["model"]] = max(best_b1.get(r["model"], 0.0), float(r["decode_tok_s_median"]))
    for sm in models("sweep"):
        sw = load("sweep", sm)
        closed = [r for r in sw.values() if r.get("kind") == "closed_loop" and r.get("steady_output_tok_s")]
        c1 = next((r for r in closed if str(r.get("concurrency")) == "1" and "None" in str(r.get("max_num_seqs"))), None)
        if c1 and (ref := best_b1.get(c1["model"])) and c1["steady_output_tok_s"] < 0.5 * ref:
            for r in closed + [sw["knee"]] * ("knee" in sw):
                r["_session_note"] = (f"clock-limited session: c=1 gave {c1['steady_output_tok_s']:.1f} tok/s vs "
                                      f"{ref:.2f} batch-1 in a stable session")
        for m in sorted({str(r["max_num_seqs"]) for r in closed}):
            top = max((r for r in closed if str(r["max_num_seqs"]) == m), key=lambda r: r["steady_output_tok_s"])
            rows.append((f"peak steady output tok/s, max-num-seqs {m}", f"{top['steady_output_tok_s']:,.1f} tok/s at c={top['concurrency']} (TTFT p95 {top.get('ttft_ms_p95'):,.0f} ms)", top["model"], top))
        if (r := sw.get("knee")):
            rows.append(("throughput knee rule (closed loop)", f"c={r['knee_concurrency']}, {r['knee_req_s']} req/s", r["model"], r))
    q = load("quant")
    for v in ("fp16", "awq-int4", "gguf-q8_0", "gguf-q4_k_m"):
        if (r := q.get(f"{v}-decode")) and r.get("decode_tok_s_median"):
            rows.append((f"{v} batch-1 decode", f"{r['decode_tok_s_median']:.2f} tok/s", r["model"], r))
        if (r := q.get(f"{v}-c16")) and r.get("steady_output_tok_s"):
            cost = f"; ${price[0] / (r['steady_output_tok_s'] * 3600) * 1e6:.3f}/1M output tokens" if price else ""
            rows.append((f"{v} c=16 steady output", f"{r['steady_output_tok_s']:,.1f} tok/s{cost}", r["model"], r))
        if (r := q.get(f"{v}-lmeval")) and r.get("lmeval"):
            for task, metric in (("gsm8k", "exact_match,flexible-extract"), ("hellaswag", "acc_norm,none")):
                m = r["lmeval"].get(task) or {}
                if metric in m:
                    se = m.get(metric.replace(",", "_stderr,", 1))
                    rows.append((f"{v} {task} {metric.split(',')[0]} ({metric.split(',')[1]}), --limit {r.get('lmeval_limit')}",
                                 f"{m[metric]:.3f}" + (f" ± {se:.3f}" if se is not None else ""), r["model"], r))
        if (r := q.get(f"{v}-ppl")) and r.get("ppl"):
            rows.append((f"{v} perplexity (wikitext-2, {r.get('ppl_chunks')}×{r.get('ppl_ctx')})", f"{r['ppl']}", r["model"], r))
    if (got := nccl_run()):
        _, nr = got
        f = nccl_facts(nr)
        if f["reps"]:
            r1 = f["reps"][0]
            r1["_session_note"] = f["note"]
            bus = ", ".join(fmt(b, 2) for b in f["bus_1g"])
            rows.append(("2×T4 all-reduce busbw @ 1 GiB (PCIe, one box)", f"{fmt(f['bus_1g_med'], 2)} GB/s (median of {len(f['bus_1g'])}: {bus})", "nccl-tests all_reduce_perf", r1))
            rows.append(("2×T4 all-reduce small-message time @ 8 B", f"{fmt(sorted(f['small_8b_us'])[len(f['small_8b_us']) // 2], 1)} µs (median of {len(f['small_8b_us'])})", "nccl-tests all_reduce_perf", r1))
            if (pc := nccl_run("p2pcheck-default")):
                pr_ = pc[1]
                d, ph = pr_.get("p2pcheck-default", {}), pr_.get("p2pcheck-p2p-level-phb", {})
                bd, bp = nccl_at(d, GIB), nccl_at(ph, GIB)
                if bd and bp:
                    wrong = (d.get("wrong_total") or 0) + (ph.get("wrong_total") or 0)
                    ph["_session_note"] = f"correctness check: {wrong} wrong values" if wrong else ""
                    rows.append(("2×T4 all-reduce P2P ÷ SHM @ 1 GiB (NCCL_P2P_LEVEL=PHB vs default, one session)", f"{bp / bd:.2f}× ({fmt(bp, 2)} GB/s {', '.join(ph.get('transports') or [])} vs {fmt(bd, 2)} GB/s {', '.join(d.get('transports') or [])})", "nccl-tests all_reduce_perf", ph))
            if (r := nr.get("allreduce-p2p-disabled")) and f["p2p_off_1g"] and f["bus_1g_med"]:
                r["_session_note"] = f["note"]
                rows.append(("2×T4 all-reduce default ÷ NCCL_P2P_DISABLE=1 @ 1 GiB", f"{f['bus_1g_med'] / f['p2p_off_1g']:.2f}× ({fmt(f['bus_1g_med'], 2)} vs {fmt(f['p2p_off_1g'], 2)} GB/s; transport {', '.join(r1.get('transports') or [])} vs {', '.join(r.get('transports') or [])})", "nccl-tests all_reduce_perf", r))
    if (got := p8x2_run()):
        d, pr = got
        res = p8x2_analysis(d)
        for c in res["conditions"]:
            h, r = c.get("headline"), pr.get(f"cond-{c['condition']}")
            if not (h and r):
                continue
            clk = {k: (v.get("gpu") or {}).get("sm_clock_mhz_mean") for k, v in c["servers"].items()}
            if clk.get("L") and clk.get("S") and abs(clk["L"] - clk["S"]) / max(clk["L"], clk["S"]) > 0.15:
                r["_session_note"] = f"SM clock L {clk['L']:.0f} vs S {clk['S']:.0f} MHz in this window"
            ph = h.get("phase_L") or {}
            if (ph.get("prefill_share_of_window") or 0) > 0.2 and ph.get("probes") and ph["probes_sent_in_prefill"] == 0:
                r = dict(r, _session_note=(r.get("_session_note", "") + "; " if r.get("_session_note") else "") +
                         f"phase-locked: 0 / {ph['probes']} L probes sent while L was prefilling "
                         f"({ph['prefill_share_of_window']:.0%} of the window) — best-case L TTFT, not random arrival")
            if h.get("n_L", 0) < 12:
                r["_session_note"] = (r.get("_session_note", "") + "; " if r.get("_session_note") else "") + \
                    f"n {h['n_L']} / {h['n_S']} < 12 planned (session budget)"
            ci = h["gap_ci95_bootstrap_s"]
            if c["condition"] != "idle" and h.get("e2e_gap_s") is not None:
                eci = h["e2e_gap_ci95_bootstrap_s"]
                rows.append((f"P8 probe e2e (128 tokens) gap L − S, {P8_COND.get(c['condition'], c['condition'])} ({P8_LABEL})",
                             f"{h['e2e_gap_s']:.2f} s (median {h['median_e2e_L_s']:.2f} vs {h['median_e2e_S_s']:.2f} s"
                             + (f"; 95 % bootstrap CI {eci[0]:.2f} … {eci[1]:.2f} s" if eci else "") + ")", r["model"], r))
            rows.append((f"P8 probe TTFT gap L − S, {P8_COND.get(c['condition'], c['condition'])} ({P8_LABEL})",
                         f"{h['gap_s']:.3f} s (median {h['median_ttft_L_s']:.3f} vs {h['median_ttft_S_s']:.3f} s, ×{h['ratio']}; "
                         f"95 % bootstrap CI {ci[0]:.3f} … {ci[1]:.3f} s; n {h['n_L']} / {h['n_S']})" if ci else f"{h['gap_s']:.3f} s",
                         r["model"], r))
        for rt in res["router"]:
            r = pr.get(f"cond-{rt['condition']}")
            if rt["n"] and r and rt["condition"] in ("main", "mns2"):
                sp, tp = rt["stock_picks"], rt["token_picks"]
                rows.append((f"P8 stock EPP profile on real gauges, {P8_COND[rt['condition']]} (computed offline from real engine metrics)",
                             f"higher score: L {sp['L']} / S {sp['S']} / tie {sp['tie']} of {rt['n']} probes; median margin "
                             f"{rt['stock_margin_median']:.4f}; token-load profile L {tp['L']} / S {tp['S']} / tie {tp['tie']}", r["model"], r))
    out = ["# RESULTS", "", "One row per headline number. Every number is from a recorded run; the link is the raw JSONL row "
           "(`key` column) with full provenance (git sha, GPU/driver/CUDA, engine version, model revision, flags, client config). "
           "Context, caveats and what is emulated: [benchmarks/results/t4/README.md](benchmarks/results/t4/README.md). "
           "Generated by `benchmarks/analyze.py`. Kaggle T4 sessions differ (some are power-capped): rows with a "
           "caveat come from an unstable or clock-limited session — compare rows only within one session and quote "
           "absolute speed from rows without a caveat.", "",
           "| result | value | caveat | model | hardware | engine | key | raw JSONL |", "|---|---|---|---|---|---|---|---|"]
    for name, val, model, r in rows:
        eng = r.get("engine") or (f"vLLM {r['vllm_version']}" if r.get("vllm_version") else None) or \
            (f"NCCL {r['nccl_version_log']}" if r.get("nccl_version_log") else "—")
        hw = f"{'2 × ' if r.get('stage') in ('nccl', 'p8x2') else ''}{r.get('gpu')} (Kaggle), driver {r.get('driver')}"
        out.append(f"| {name} | {val} | {caveat(r)} | `{model}` | {hw} | {eng} | `{r['key']}` | [{Path(r['_src']).parts[3]}]({r['_src']}) |")
    return out + [""]


def results_md(price: tuple[float, str] | None) -> str:
    """RESULTS.md = generated T4 headline table + the hand-curated lab table (benchmarks/results/lab_headlines.md)."""
    out = ["## T4 engine results (Kaggle, real GPU)", ""] + headlines(price)[2:]
    lab = REPO / "benchmarks" / "results" / "lab_headlines.md"
    head = ["# RESULTS", "", "Every number below comes from a recorded run. T4 rows are generated from the raw JSONL; lab rows link "
            "the write-up with the method and raw files. Sections: [T4 engine results](#t4-engine-results-kaggle-real-gpu) · "
            "[Lab results](#lab-results-k3s--k3d-on-the-workstation).", ""]
    return "\n".join(head + out + ([lab.read_text().rstrip(), ""] if lab.exists() else [])) + "\n"


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
    all_facts = []
    for m in models("baseline"):
        facts = section_baseline(load("baseline", m), out, T4)
        if (q := load("quant", m).get("fp16-decode")) and facts:
            facts |= {"decode_quant": q.get("decode_tok_s_median"), "decode_quant_spread": q.get("decode_spread_pct")}
        all_facts.append(facts)
    for facts in all_facts:
        section_predictions(facts, out)
    kv = load("kvgrid")
    out += ["## Task 2 — KV capacity (8B AWQ INT4)", "", "Full table: [benchmarks/kv_capacity_table.md](../../kv_capacity_table.md).", ""]
    (REPO / "benchmarks" / "kv_capacity_table.md").write_text("\n".join(section_kv(kv, REPO / "benchmarks")) + "\n")
    for m in models("sweep"):
        section_sweep(load("sweep", m), out, T4)
    section_quant(load("quant"), out, T4, price)
    section_nccl(out, T4)
    section_p8x2(out, T4)
    section_runs(out)
    (T4 / "summary.md").write_text("\n".join(out) + "\n")
    (REPO / "RESULTS.md").write_text(results_md(price))
    print(f"wrote {T4 / 'summary.md'}, {REPO / 'benchmarks' / 'kv_capacity_table.md'}, charts in {CHARTS}")


if __name__ == "__main__":
    main()
