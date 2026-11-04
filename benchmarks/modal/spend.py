"""Modal spend of this build, attributed by app id (other runs may share the workspace).

    .venv/bin/python benchmarks/modal/spend.py --add RUN_ID TASK APP_ID [--note TEXT]   # register a launched app
    .venv/bin/python benchmarks/modal/spend.py                                          # refresh spend.md + runs.jsonl

Source: `modal billing report --for today -r h --show-resources --json` (UTC day 2026-11-03) (Modal's own per-object cost records;
hourly buckets, the current hour included as far as Modal has billed it). Only apps listed in
benchmarks/results/h100/runs.jsonl or whose description is APP_DESC are counted. GPU-seconds are CALCULATED from the
H100 cost at the published rate (`modal billing rates`: $3.95 / h).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "benchmarks" / "results" / "h100"
RUNS = OUT / "runs.jsonl"
APP_DESC = "goodput-h100"
START = "2026-11-03"
H100_PER_H = 3.95


def report() -> list[dict]:
    cmd = ["modal", "billing", "report", "--for", "today", "-r", "h", "--show-resources", "--json"]   # UTC day; all of this build
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def load_runs() -> list[dict]:
    return [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()] if RUNS.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--add", nargs=3, metavar=("RUN_ID", "TASK", "APP_ID"))
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    runs = load_runs()
    if a.add:
        run_id, task, app_id = a.add
        runs.append({"run_id": run_id, "task": task, "app_id": app_id, "note": a.note,
                     "registered_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    rows = report()
    by_app: dict = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r.get("description") == APP_DESC or r["object_id"] in {x["app_id"] for x in runs}:
            by_app[r["object_id"]][r["resource"]] += float(r["cost"])
    known = {x["app_id"] for x in runs}
    for app_id in by_app:
        if app_id not in known:
            runs.append({"run_id": None, "task": "other (build / failed start)", "app_id": app_id, "note": "found in billing report"})
    t = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = defaultdict(float)
    for x in runs:
        c = by_app.get(x["app_id"], {})
        x["cost_usd_by_resource"] = {k: round(v, 6) for k, v in sorted(c.items())}
        x["cost_usd"] = round(sum(c.values()), 4)
        x["h100_gpu_s_calculated"] = round(c.get("H100", 0) / H100_PER_H * 3600, 1)
        x["cost_source"] = f"modal billing report (read {t})"
        for k, v in c.items():
            total[k] += v
    RUNS.write_text("".join(json.dumps(x) + "\n" for x in runs))
    lines = ["# Modal spend (this build)", "",
             f"Source: `modal billing report --for today -r h --show-resources --json` (UTC {START}), read {t}; attributed by app id "
             f"(description `{APP_DESC}`). GPU-seconds CALCULATED = H100 cost ÷ ${H100_PER_H}/h. Modal bills the H100 from "
             "container start to stop, so it includes the image load / container boot before the function runs.", "",
             "| run | task | app | H100 $ | CPU $ | memory $ | other $ | total $ | H100 GPU-s (CALCULATED) | note |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for x in runs:
        c = x["cost_usd_by_resource"]
        other = sum(v for k, v in c.items() if k not in ("H100", "CPU", "Memory"))
        lines.append(f"| {x['run_id'] or '—'} | {x['task']} | `{x['app_id']}` | {c.get('H100', 0):.4f} | {c.get('CPU', 0):.4f} | "
                     f"{c.get('Memory', 0):.4f} | {other:.4f} | **{x['cost_usd']:.4f}** | {x['h100_gpu_s_calculated']:.0f} | {x.get('note', '')} |")
    tot = sum(total.values())
    lines.append(f"| **total** | | | {total.get('H100', 0):.4f} | {total.get('CPU', 0):.4f} | {total.get('Memory', 0):.4f} | "
                 f"{tot - total.get('H100', 0) - total.get('CPU', 0) - total.get('Memory', 0):.4f} | **{tot:.4f}** | "
                 f"{total.get('H100', 0) / H100_PER_H * 3600:.0f} ({total.get('H100', 0) / H100_PER_H:.3f} GPU-h) | |")
    (OUT / "spend.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
