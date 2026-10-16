#!/usr/bin/env python3
"""#21: summarize scripts/probe_capacity.py runs: per level, label (on/off) and path, mean and min-max over runs.

Usage: .venv/bin/python scripts/capacity_summary.py benchmarks/results/probes/capacity/20261016-*-{on,off}.jsonl
CPU columns: client = load generator CPU-s per s (1.0 = one core busy); EPP and gateway = kubectl top millicores
(gateway summed over its pods), sampled once at the end of each level.
"""
import collections, json, pathlib, statistics, sys


def millicores(top_lines):
    total = 0
    for line in top_lines:
        cols = line.split()
        if len(cols) >= 2 and cols[1].endswith("m"):
            total += int(cols[1][:-1])
    return total if top_lines else None


def fmt(values, digits=0):
    mean = statistics.mean(values)
    return f"{mean:.{digits}f} ({min(values):.{digits}f}–{max(values):.{digits}f})"


def main(paths):
    rows = collections.defaultdict(list)
    for path in paths:
        for line in pathlib.Path(path).read_text().splitlines():
            r = json.loads(line)
            rows[(r["conc"], r["label"], r["path"])].append(r)
    print("| conc | plugin | path | runs | rps | p50 ms | p99 ms | errors | client CPU | EPP m | gateway m (sum) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for (conc, label, path) in sorted(rows, key=lambda k: (k[0], k[1], k[2])):
        rs = rows[(conc, label, path)]
        epp = [millicores(r["epp_top"]) for r in rs if r.get("epp_top")]
        gw = [millicores(r["gw_top"]) for r in rs if r.get("gw_top")]
        print(f"| {conc} | {label} | {path} | {len(rs)} | {fmt([r['rps'] for r in rs], 1)} | {fmt([r['p50_ms'] for r in rs])} | "
              f"{fmt([r['p99_ms'] for r in rs])} | {sum(r['errors'] for r in rs)} | {fmt([r['client_cpu'] for r in rs], 2)} | "
              f"{fmt(epp) if epp else '-'} | {fmt(gw) if gw else '-'} |")


if __name__ == "__main__":
    main(sys.argv[1:])
