"""Summarize e5-shaped-results.json into the E5 shaped table (markdown).

Receiver job time = max over pairs of the receiver's last-byte time: the end of
the 0.1 s server interval in which the cumulative received bytes reach the
pair total (`iperf3 -s -i 0.1 -J`, fetched with `--get-server-output`),
offset by the client's synchronized start. Resolution 0.1 s (upper edge).
Client-exit job time also includes iperf3's end-of-test exchange, which this
lab measured as snapping to whole seconds for single-stream tests. Both are
measured; neither is a model.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from fabric.experiments.e5_shaped import RESULT_PATH


def transfer_time(cell: dict) -> float:
    return cell["receiver_job_time_seconds"]


def summarize(path: Path = RESULT_PATH) -> list[dict]:
    cells = json.loads(path.read_text())["cells"]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for cell in cells:
        groups[(cell["pattern"], cell["routing"], cell["flows_per_pair"])].append(cell)
    rows = []
    for (pattern, routing, flows), items in groups.items():
        rows.append({
            "pattern": pattern, "routing": routing, "flows": flows, "repeats": len(items),
            "transfer": [transfer_time(c) for c in items],
            "client_exit": [c["job_time_seconds"] for c in items],
            "bound": [c["max_link_bound_seconds"] for c in items],
            "imbalance": [c["worst_leaf_imbalance"] for c in items],
            "drops": [c["qdisc_drops_total"] for c in items],
            "retransmits": [sum(p["retransmits"] or 0 for p in c["pairs"]) for c in items],
            "cpu_max_cores": [max(c["cpu"]["container_cpu_cores"].values()) for c in items],
            "system_busy": [c["cpu"]["system_busy_percent"] for c in items],
            "skew_ms": [1000 * c["start_skew_seconds"] for c in items],
        })
    pinned = {(r["pattern"], r["flows"]): statistics.mean(r["transfer"]) for r in rows if r["routing"] == "pinned"}
    for row in rows:
        row["gap_vs_pinned"] = statistics.mean(row["transfer"]) - pinned.get((row["pattern"], row["flows"]), float("nan"))
    order = {"ring": 0, "all-to-all": 1, "pinned": 0, "L3": 1, "L4": 2}
    return sorted(rows, key=lambda r: (order[r["pattern"]], order[r["routing"]], r["flows"]))


def fmt(values: list[float], digits: int = 2) -> str:
    return " / ".join(f"{v:.{digits}f}" for v in values)


def main() -> None:
    print("| Pattern | Routing | Flows/pair | Max/mean (r1/r2/r3) | Max-link bound s | Receiver job s (r1/r2/r3) | Mean | Gap vs pinned s | Client-exit s | TBF drops | Retx | Max host CPU cores | VM busy % |")
    print("|---|---|---:|---|---|---|---:|---:|---|---|---|---:|---:|")
    for r in summarize():
        print(
            f"| {r['pattern']} | {r['routing']} | {r['flows']} | {fmt(r['imbalance'], 3)} | {fmt(r['bound'])} | "
            f"{fmt(r['transfer'])} | {statistics.mean(r['transfer']):.2f} | {r['gap_vs_pinned']:+.2f} | "
            f"{fmt(r['client_exit'])} | {' / '.join(map(str, r['drops']))} | {' / '.join(map(str, r['retransmits']))} | "
            f"{max(r['cpu_max_cores']):.2f} | {max(r['system_busy']):.0f} |"
        )
    rows = summarize()
    transfer = [t for r in rows for t in r["transfer"]]
    bound = [b for r in rows for b in r["bound"]]
    residual = [t - b for t, b in zip(transfer, bound)]
    print(f"\ncells={len(transfer)} receiver-job-minus-bound: min {min(residual):.3f} max {max(residual):.3f} mean {statistics.mean(residual):.3f}")
    print(f"start skew max ms: {max(s for r in rows for s in r['skew_ms']):.2f}")


if __name__ == "__main__":
    main()
