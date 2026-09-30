"""Run directory layout and retention.

    <results_dir>/<YYYYmmdd-HHMMSS>_<experiment>/
        manifest.json        provenance + resolved config + sweep        (small, committed)
        summary.csv          one row per sweep point                     (small, committed)
        <point>/summary.json per-point summary incl. memory lines        (small, committed)
        <point>/requests.jsonl, metrics.jsonl, server.log.gz, bench.jsonl (raw, git-ignored, pruned)

Retention keeps summaries forever and prunes RAW files of all but the newest
`keep_raw_runs` runs per experiment. A run containing a `.keep` file is never pruned.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

RAW_PATTERNS = ("requests.jsonl", "metrics.jsonl", "server.log.gz", "server.log", "probe.log.gz", "bench.jsonl")


def new_run_dir(results_dir: Path, experiment: str) -> Path:
    run = results_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{experiment}"
    run.mkdir(parents=True, exist_ok=False)
    return run


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


def write_jsonl(path: Path, rows) -> None:
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    fields: list[str] = []
    for row in rows:
        fields += [k for k in row if k not in fields]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def prune(results_dir: Path, experiment: str, keep: int) -> list[Path]:
    """Delete raw files from older runs of `experiment`; return runs that were pruned."""
    runs = sorted(p for p in results_dir.glob(f"*_{experiment}") if p.is_dir())
    pruned = []
    for run in runs[:-keep] if keep > 0 else runs:
        if (run / ".keep").exists():
            continue
        raw = [p for pat in RAW_PATTERNS for p in run.rglob(pat)]
        for p in raw:
            p.unlink()
        if raw:
            pruned.append(run)
    return pruned
