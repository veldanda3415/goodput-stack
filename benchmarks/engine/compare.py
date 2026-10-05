"""Put two engine runs side by side (typically real llama.cpp vs the simulator calibrated to it).

    python -m benchmarks.engine.compare <run_dir_A> <run_dir_B> [--metrics ttft_ms_p50,tpot_ms_p50] [--out FILE]

Rows are joined on the sweep parameters both runs share; llama.cpp `parallel` and the
simulator's `max-num-seqs` count as the same axis ("slots"). Δ = (B − A) / A.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from ..harness.report import LABELS, _engine, _fmt, _num

DEFAULT_METRICS = ["ttft_ms_p50", "ttft_ms_p95", "tpot_ms_p50", "itl_ms_p50", "e2e_ms_p50",
                   "steady_output_tok_s", "agg_output_tok_s", "slo_attainment_pct", "m_deferred_max"]
ALIASES = {"parallel": "slots", "max-num-seqs": "slots"}


def load(run_dir: Path) -> tuple[dict, list[dict], list[str]]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    with open(run_dir / "summary.csv") as f:
        rows = [r for r in csv.DictReader(f) if r.get("status") == "ok"]
    params = []
    for key in manifest.get("sweep", {}):
        name = key.split(".")[-1]
        params.append(ALIASES.get(name, name))
        for r in rows:
            r[ALIASES.get(name, name)] = r.get(name)
    return manifest, rows, params


def _key(row: dict, params: list[str]) -> tuple:
    return tuple(_num(row.get(p)) for p in params)


def render(a_dir: Path, b_dir: Path, metrics: list[str]) -> str:
    (ma, ra, pa), (mb, rb, pb) = load(a_dir), load(b_dir)
    params = [p for p in pa if p in pb]
    metrics = [m for m in metrics if any(r.get(m) not in (None, "") for r in ra) and
               any(r.get(m) not in (None, "") for r in rb)]
    by_b = {_key(r, params): r for r in rb}
    lines = [f"# Compare: {ma['config']['experiment']} vs {mb['config']['experiment']}", ""]
    for tag, m, d in (("A", ma, a_dir), ("B", mb, b_dir)):
        si = m.get("system", {})
        lines.append(f"- **{tag}** `{d.name}`: {_engine(si)} · {m.get('target')} · **{si.get('measurement')}**")
    only = sorted(set(pa) ^ set(pb))
    lines += [f"- joined on: {', '.join(params) or 'nothing (single point each)'}"
              + (f"; not shared (ignored): {', '.join(only)}" if only else ""), ""]
    head = params + [f"{LABELS.get(m, m)} {t}" for m in metrics for t in ("A", "B", "Δ")]
    lines += ["| " + " | ".join(head) + " |", "|" + "---:|" * len(head)]
    matched = 0
    for r in ra:
        other = by_b.get(_key(r, params))
        if other is None:
            continue
        matched += 1
        cells = [_fmt(_num(r.get(p))) for p in params]
        for m in metrics:
            x, y = _num(r.get(m)), _num(other.get(m))
            delta = f"{(y - x) / x * 100:+.0f}%" if x and y is not None else "–"
            cells += [_fmt(x), _fmt(y), delta]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", f"{matched} matched point(s) of {len(ra)} (A) / {len(rb)} (B)."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--metrics", default=",".join(DEFAULT_METRICS), help="comma-separated summary keys")
    ap.add_argument("--out", type=Path, help="also write the markdown here")
    args = ap.parse_args(argv)
    text = render(args.a, args.b, [m for m in args.metrics.split(",") if m])
    print(text)
    if args.out:
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
