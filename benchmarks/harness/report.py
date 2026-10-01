"""Human-readable REPORT.md for a run: curated columns with units, fixed settings,
what-to-look-for notes and derived numbers. summary.csv stays the machine format.

Per-experiment layout comes from the config (`experiments.<name>.report`):
    report:
      columns: [prompt_tokens, ttft_ms_p50, ...]   # keys from summary rows
      look_for: "..."                              # shown under the title
      derive: [prefill_rate, kv_per_token, ...]    # names in DERIVE below
Regenerate for an existing run: `python -m benchmarks.engine.run --report <run_dir>`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

# key -> column header (unit in brackets). Unknown keys fall back to the raw key.
LABELS = {
    "status": "status",
    "parallel": "slots (-np)",
    "concurrency": "clients",
    "prompt_tokens": "prompt [tok]",
    "ctx_size": "ctx (-c)",
    "threads": "threads",
    "scrape_interval_s": "scrape every [s]",
    "requests_ok": "ok reqs",
    "ttft_ms_p50": "TTFT p50 [ms]",
    "ttft_ms_p95": "TTFT p95 [ms]",
    "ttft_ms_max": "TTFT max [ms]",
    "srv_prompt_ms_p50": "server prefill p50 [ms]",
    "ttft_minus_srv_prompt_ms_p50": "TTFT - prefill p50 [ms]",
    "ttft_minus_srv_prompt_ms_p95": "TTFT - prefill p95 [ms]",
    "itl_ms_p50": "ITL p50 [ms]",
    "itl_ms_p95": "ITL p95 [ms]",
    "tpot_ms_p50": "TPOT p50 [ms]",
    "tpot_ms_p95": "TPOT p95 [ms]",
    "slo_attainment_pct": "SLO met [%]",
    "goodput_tok_s": "goodput [tok/s]",
    "steady_output_tok_s": "steady output [tok/s]",
    "steady_output_tok_s_spread_pct": "± spread [%]",
    "agg_output_tok_s_spread_pct": "± spread [%]",
    "tpot_ms_p50_spread_pct": "TPOT ± [%]",
    "ttft_ms_p95_spread_pct": "TTFT p95 ± [%]",
    "repeats": "repeats",
    "e2e_ms_p50": "E2E p50 [ms]",
    "e2e_ms_p95": "E2E p95 [ms]",
    "agg_output_tok_s": "total output [tok/s]",
    "srv_decode_tok_s_mean": "per-request decode [tok/s]",
    "kv_buffer_mib": "KV cache [MiB]",
    "model_buffer_mib": "weights [MiB]",
    "compute_buffer_mib": "compute buf [MiB]",
    "rss_after_load_mib": "RSS idle [MiB]",
    "rss_peak_mib": "RSS peak [MiB]",
    "startup_s": "startup [s]",
    "m_deferred_max": "max queued (deferred)",
    "m_processing_max": "max processing",
    "m_scrapes": "scrapes",
    "m_gauge_pred_tok_s_mean_nonzero": "gauge predicted_tokens_seconds (non-zero mean)",
    "m_gauge_zero_windows": "windows where gauge = 0",
    "m_counter_per_slot_tok_s": "counters: tokens / slot-seconds",
    "m_counter_wall_tok_s": "counters: tokens / wall-seconds",
    "m_idle_gauge_2nd": "gauge after 1 s idle",
    "gen_tok_s": "decode [tok/s]",
    "gen_tok_s_stddev": "± stddev",
    "effective_bw_gb_s": "effective bandwidth [GB/s]",
}


def _fmt(v) -> str:
    if v is None or v == "":
        return "–"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e6:
        return f"{int(v):,}"
    if isinstance(v, float):
        return f"{v:,.1f}" if abs(v) >= 10 else f"{v:.2f}"
    return str(v)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Least-squares y = a + b*x; returns (a, b)."""
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pts) < 2:
        return None
    n = len(pts)
    mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return None
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    return my - b * mx, b


def _ok(rows):
    return [r for r in rows if r.get("status") == "ok"]


# ---------------------------------------------------------------- derived numbers

def prefill_rate(rows, manifest):
    """Prefill cost per prompt length. Not a single line: fixed overhead dominates short
    prompts and attention cost grows with length, so a linear fit misleads."""
    rows = [r for r in _ok(rows) if _num(r.get("concurrency", 1)) in (None, 1.0)] or _ok(rows)
    pts = [(_num(r.get("prompt_tokens") or r.get("prompt_n_mean")), _num(r.get("srv_prompt_ms_p50"))) for r in rows]
    pts = sorted((n, ms) for n, ms in pts if n and ms)
    if not pts:
        return []
    per = "; ".join(f"{n:,.0f} tok → {ms / n:.2f} ms/tok ({n / ms * 1000:,.0f} tok/s)" for n, ms in pts)
    out = [f"Prefill cost by prompt length (server): {per}"]
    best = min(pts, key=lambda p: p[1] / p[0])
    out.append(f"**Fastest prefill: {best[0] / best[1] * 1000:,.0f} tok/s at {best[0]:,.0f} tokens**; shorter prompts pay "
               f"fixed overhead, longer ones pay growing attention cost")
    big = [p for p in pts if p[0] >= 1000]
    if big:
        n, ms = big[-1]
        out.append(f"Rule of thumb on this host: a {n:,.0f}-token prompt costs ≈ {ms / 1000:.1f} s TTFT for one user before any queueing")
    return out


def kv_per_token(rows, manifest):
    rows = _ok(rows)
    xs = [_num(r.get("ctx_size")) for r in rows]
    out = []
    fit = _fit(xs, [_num(r.get("kv_buffer_mib")) for r in rows])
    if fit:
        out.append(f"KV cache cost (slope): **{fit[1] * 1024:.2f} KiB/token** "
                   f"(theory for Qwen2.5-0.5B f16: 2 × 24 layers × 2 kv-heads × 64 dim × 2 B = 12 KiB)")
    fit = _fit(xs, [_num(r.get("rss_peak_mib")) for r in rows])
    if fit:
        out.append(f"RSS peak grows {fit[1] * 1024:.2f} KiB per context token; baseline ≈ {fit[0]:,.0f} MiB")
    return out


def queueing(rows, manifest):
    out = []
    for r in _ok(rows):
        slots, clients = _num(r.get("parallel")), _num(r.get("concurrency"))
        wait = _num(r.get("ttft_minus_srv_prompt_ms_p50"))
        if slots and clients and clients > slots and wait is not None:
            out.append(f"slots={slots:.0f}, clients={clients:.0f}: {clients - slots:.0f} request(s) wait for a slot; "
                       f"TTFT − prefill p50 = {wait:,.0f} ms")
    return out[:12]


def bandwidth(rows, manifest):
    sysinfo = manifest.get("system", {})
    best = max(_ok(rows), key=lambda r: _num(r.get("effective_bw_gb_s")) or 0, default=None)
    out = []
    if best:
        out.append(f"Best effective bandwidth: **{_num(best['effective_bw_gb_s']):.1f} GB/s** at {best.get('threads') or manifest.get('config', {}).get('server', {}).get('threads')} threads "
                   f"({_num(best['gen_tok_s']):.1f} tok/s × {int(_num(best['model_bytes'])) / 1e6:.0f} MB weights)")
    if sysinfo.get("memcopy_1thread_gb_s"):
        out.append(f"Single-thread memcpy reference: {sysinfo['memcopy_1thread_gb_s']} GB/s "
                   f"(DDR4-2933 dual-channel theoretical peak ≈ 46.9 GB/s, if that's what is installed)")
    return out


def metrics_semantics(rows, manifest):
    out = []
    for r in _ok(rows):
        out.append(
            f"scrape every {r.get('scrape_interval_s')} s: gauge `predicted_tokens_seconds` (non-zero mean) "
            f"{_fmt(_num(r.get('m_gauge_pred_tok_s_mean_nonzero')))} tok/s vs per-request decode "
            f"{_fmt(_num(r.get('srv_decode_tok_s_mean')))} vs real server throughput {_fmt(_num(r.get('agg_output_tok_s')))}; "
            f"gauge = 0 in {r.get('m_gauge_zero_windows')}/{r.get('m_scrapes')} windows; after 1 s idle: {r.get('m_idle_gauge_2nd')}")
    if out:
        out.append("Reading: a gauge matching per-request decode (not throughput) means it reports how fast ONE "
                   "request decodes, averaged over requests that finished since the last scrape; zero windows = no "
                   "request finished in that window. Don't use it as server throughput or for autoscaling - use "
                   "rate(tokens_predicted_total[1m]) instead.")
    return out


def saturation(rows, manifest):
    """Find the knee / optimum of a concurrency sweep (throughput vs per-user latency)."""
    rows = sorted((r for r in _ok(rows) if _num(r.get("concurrency"))), key=lambda r: _num(r["concurrency"]))
    if len(rows) < 2:
        return []
    c = lambda r: int(_num(r["concurrency"]))
    # Steady-window throughput (all clients busy) when available; whole-run otherwise.
    key = "steady_output_tok_s" if any(_num(r.get("steady_output_tok_s")) for r in rows) else "agg_output_tok_s"
    tput = lambda r: _num(r.get(key)) or 0
    base = rows[0]
    out = [f"Throughput basis: `{key}`" + (" (only the window where every client is busy)" if key.startswith("steady") else "")]

    scale = []
    prev = None
    for r in rows:
        eff = tput(r) / (c(r) / c(base) * tput(base)) * 100 if tput(base) else 0
        gain = f", {(tput(r) / tput(prev) - 1) * 100:+.0f}% vs {c(prev)}" if prev and tput(prev) else ""
        scale.append(f"{c(r)}→{tput(r):,.0f} tok/s ({eff:.0f}% linear{gain})")
        prev = r
    out.append("Scaling: " + "; ".join(scale))

    best = max(rows, key=tput)
    out.append(f"**Max throughput**: {tput(best):,.0f} tok/s at {c(best)} clients "
               f"(TPOT p50 {_fmt(_num(best.get('tpot_ms_p50')))} ms, TTFT p95 {_fmt(_num(best.get('ttft_ms_p95')))} ms)")

    knee = next(r for r in rows if tput(r) >= 0.9 * tput(best))
    spreads = [_num(r.get(f"{key}_spread_pct")) for r in rows if _num(r.get(f"{key}_spread_pct")) is not None]
    if spreads:
        out.append(f"Repeat spread of throughput: up to {max(spreads):.1f}% "
                   + ("(> 10%: knee may move by one level - treat as a range)" if max(spreads) > 10 else "(stable)"))
    out.append(f"90%-of-max point: {c(knee)} clients, {tput(knee):,.0f} tok/s, "
               f"TPOT p50 {_fmt(_num(knee.get('tpot_ms_p50')))} ms vs {_fmt(_num(base.get('tpot_ms_p50')))} ms at {c(base)}")

    # Kleinrock "power" = throughput / latency: peaks where extra load stops being worth its delay.
    tpot = lambda r: _num(r.get("tpot_ms_p50"))
    powered = [r for r in rows if tpot(r)]
    if powered:
        pk = max(powered, key=lambda r: tput(r) / tpot(r))
        out.append(f"**Knee (max power = throughput / TPOT)**: **{c(pk)} clients** - {tput(pk):,.0f} tok/s at "
                   f"TPOT p50 {_fmt(tpot(pk))} ms; beyond it each extra client costs more latency than it adds throughput")

    peak_i = rows.index(best)
    after = rows[peak_i + 1:]
    if after and all(tput(r) < tput(best) * 0.95 for r in after[-1:]):
        drop = next(r for r in after if tput(r) < tput(best) * 0.95)
        out.append(f"**Over-saturation**: after the peak, throughput falls to {tput(drop):,.0f} tok/s at {c(drop)} clients")
    dips = [c(r) for a, r in zip(rows[:peak_i], rows[1:peak_i + 1]) if tput(r) < tput(a) * 0.98]
    if dips:
        out.append(f"Non-monotonic dip before the peak at {dips} clients (check spread; likely scheduling noise, not saturation)")
    queued = next((r for r in rows if (_num(r.get("m_deferred_max")) or 0) > 0), None)
    if queued:
        out.append(f"Slot queueing starts at {c(queued)} clients (max queued {_fmt(_num(queued.get('m_deferred_max')))})")

    slo = manifest.get("config", {}).get("slo") or {}
    if any(r.get("goodput_tok_s") not in (None, "") for r in rows):
        g = lambda r: _num(r.get("goodput_tok_s")) or 0
        gbest = max(rows, key=g)
        ok_all = [r for r in rows if (_num(r.get("slo_attainment_pct")) or 0) >= 99]
        out.append(f"**SLO optimum** (TTFT ≤ {slo.get('ttft_ms')} ms, TPOT ≤ {slo.get('tpot_ms')} ms): "
                   f"max goodput {g(gbest):,.0f} tok/s at {c(gbest)} clients "
                   f"({_fmt(_num(gbest.get('slo_attainment_pct')))}% of requests in SLO); "
                   f"highest load with ≥99% in SLO: {c(ok_all[-1]) if ok_all else 'none'} clients")
    return out


DERIVE = {"saturation": saturation, "prefill_rate": prefill_rate, "kv_per_token": kv_per_token,
          "queueing": queueing, "bandwidth": bandwidth, "metrics_semantics": metrics_semantics}


# ---------------------------------------------------------------- render

def _fixed_settings(cfg: dict, swept: set[str]) -> list[str]:
    keys = {
        "server": ["ctx_size", "parallel", "threads", "kv_unified", "cache_ram_mib"],
        "client": ["prompt_tokens", "max_tokens", "concurrency", "requests", "warmup", "cache_prompt", "ignore_eos"],
    }
    out = []
    for section, names in keys.items():
        vals = [f"{n}={cfg.get(section, {}).get(n)}" for n in names
                if f"{section}.{n}" not in swept and n in cfg.get(section, {})]
        if vals and not (cfg.get("kind") == "llama_bench" and section == "client"):
            out.append(f"- **{section}**: " + ", ".join(vals))
    return out


def render(run_dir: Path, rows: list[dict] | None = None, view: dict | None = None) -> str:
    """`view` (a `report:` block) overrides the one saved in the run's manifest."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if view is not None:
        manifest["config"]["report"] = view
    if rows is None:
        with open(run_dir / "summary.csv") as f:
            rows = list(csv.DictReader(f))
    cfg = manifest["config"]
    sweep = manifest.get("sweep", {})
    view = cfg.get("report", {})
    params = [k.split(".")[-1] for k in sweep]
    columns = params + [c for c in view.get("columns", ["status", "ttft_ms_p50", "itl_ms_p50", "agg_output_tok_s"])
                        if c not in params]
    if any(r.get("status") not in ("ok", None) for r in rows) and "status" not in columns:
        columns.append("status")
    sysinfo = manifest.get("system", {})

    lines = [
        f"# {cfg['experiment']} — {manifest.get('suite', '?')} suite",
        "",
        f"{' '.join((cfg.get('description') or '').split())}",
        "",
        f"- **target**: {manifest.get('target', '?')}  ·  **measurement**: {sysinfo.get('measurement', '?')}",
        f"- **when**: {sysinfo.get('timestamp_utc')}  ·  **host**: {sysinfo.get('cpu')}, "
        f"{sysinfo.get('mem_total_mib')} MiB RAM{', WSL2' if sysinfo.get('wsl2') else ''}",
        f"- **llama.cpp**: {sysinfo.get('llama_cpp_commit')}{' (dirty)' if sysinfo.get('llama_cpp_dirty') else ''}  ·  "
        f"**model**: {sysinfo.get('model_file') or sysinfo.get('model_hf_repo')}",
        f"- **swept**: {', '.join(f'`{k}` = {v}' for k, v in sweep.items()) or 'nothing'}",
        *_fixed_settings(cfg, set(sweep)),
        "",
    ]
    if view.get("look_for"):
        lines += ["## What to look for", "", " ".join(view["look_for"].split()), ""]

    lines += ["## Results", "", "| " + " | ".join(LABELS.get(c, c) for c in columns) + " |",
              "|" + "|".join("---:" for _ in columns) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(_fmt(_num(r.get(c)) if _num(r.get(c)) is not None and c not in params else r.get(c))
                                       for c in columns) + " |")
    lines.append("")

    derived = [line for name in view.get("derive", []) if name in DERIVE for line in DERIVE[name](rows, manifest)]
    if derived:
        lines += ["## Derived", "", *[f"- {d}" for d in derived], ""]

    lines += ["## Files", "",
              "- `summary.csv` — every metric for every point (for pandas/notebooks); percentiles are p50/p95/p99/max",
              "- `<point>/summary.json` — same plus memory log lines; `<point>/requests.jsonl` — one line per request",
              "- `<point>/metrics.jsonl` — /metrics + /slots samples; `<point>/server.log.gz` — server log (capped)",
              ""]
    return "\n".join(lines)


def write(run_dir: Path, rows: list[dict] | None = None, view: dict | None = None) -> Path:
    path = run_dir / "REPORT.md"
    path.write_text(render(run_dir, rows, view))
    return path


def terminal_table(rows: list[dict], cfg: dict, sweep: dict) -> str:
    params = [k.split(".")[-1] for k in sweep]
    columns = params + [c for c in cfg.get("report", {}).get("columns", []) if c not in params]
    if any(r.get("status") != "ok" for r in rows) and "status" not in columns:
        columns.append("status")
    columns = [c for c in columns if any(r.get(c) is not None for r in rows)]
    head = [LABELS.get(c, c) for c in columns]
    cells = [[_fmt(r.get(c)) for c in columns] for r in rows]
    widths = [max(len(h), *(len(row[i]) for row in cells)) for i, h in enumerate(head)] if cells else [len(h) for h in head]
    out = ["  ".join(h.rjust(w) for h, w in zip(head, widths))]
    out += ["  ".join(v.rjust(w) for v, w in zip(row, widths)) for row in cells]
    return "\n".join(out)


def _section(text: str, heading: str) -> list[str]:
    """Lines of a `## heading` section of a REPORT.md (without the heading)."""
    lines, out, inside = text.splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip() == heading
            continue
        if inside and line.strip():
            out.append(line)
    return out


def render_index(done: list, total_s: float) -> str:
    """One page over a batch: status, duration, link and derived findings per experiment."""
    lines = ["# Engine benchmark batch", ""]
    first = next((d for d in done if d[2] and (d[2] / "manifest.json").exists()), None)
    if first:
        m = json.loads((first[2] / "manifest.json").read_text())
        si = m.get("system", {})
        lines += [f"- **started**: {si.get('timestamp_utc')}  ·  **total**: {total_s / 60:.0f} min",
                  f"- **host**: {si.get('cpu')}, {si.get('mem_total_mib')} MiB RAM{', WSL2' if si.get('wsl2') else ''}",
                  f"- **llama.cpp**: {si.get('llama_cpp_commit')}  ·  **model**: {si.get('model_file')}",
                  f"- **target**: {m.get('target')}  ·  **measurement**: {si.get('measurement')}", ""]
    lines += ["| experiment | status | duration | report |", "|---|---|---:|---|"]
    for name, status, run_dir, secs in done:
        link = f"[{run_dir.name}/REPORT.md]({run_dir.name}/REPORT.md)" if run_dir and (run_dir / "REPORT.md").exists() else "–"
        lines.append(f"| `{name}` | {status} | {secs / 60:.1f} min | {link} |")
    lines.append("")
    for name, status, run_dir, _ in done:
        if not run_dir or not (run_dir / "REPORT.md").exists():
            continue
        text = (run_dir / "REPORT.md").read_text()
        derived = _section(text, "Derived")
        table = _section(text, "Results")
        lines += [f"## {name}", ""]
        lines += (derived or table) + [""]
    return "\n".join(lines)
