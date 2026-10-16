"""Timeline for the E6 restore-transient runs (#32), from e6-restore-results.json.

Times are seconds after the restore command (Unix clock; see e6_restore).
Kernel events come from `ip -ts monitor`, BFD/BGP state from the 10 Hz poller.

Usage: python -m fabric.experiments.e6_restore_report [--label before|after] > e6-restore-<label>-table.txt
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from fabric.experiments.e6_restore import GAP, RESULT_PATH, SPINE1_PORT_ON_LEAF

LEAVES = ("leaf1", "leaf2", "leaf3", "leaf4")


def report(run: dict[str, Any]) -> list[str]:
    restore = next(e["t"] for e in run["events"] if e["event"] == "restore")
    monitor = run["monitor_full"]

    def rel(t: float | None) -> float | None:
        return None if t is None else round(t - restore, 2)

    def after(node: str, test) -> list[float]:
        return [e["t"] for e in monitor[node] if "t" in e and e["t"] >= restore and test(e["line"])]

    def poll_first(node: str, test) -> float | None:
        return next((s["t"] for s in run["poll"][node] if "t" in s and s["t"] >= restore and test(s)), None)

    up = after("spine1", lambda l: "state UP" in l and ": eth" in l)
    dad = after("spine1", lambda l: l.startswith("local fe80"))
    fib = after("spine1", lambda l: "proto bgp" in l and "nhid" in l)
    lines = [f"RUN {run['run']} ({run.get('label')}): spine1 links up +{rel(min(up))}; "
             f"spine1 link-local DAD done +{rel(min(dad))}..+{rel(max(dad))}; "
             f"spine1 first/last BGP FIB install +{rel(min(fib))}/+{rel(max(fib))}"]
    port = SPINE1_PORT_ON_LEAF
    for leaf in LEAVES:
        group = after(leaf, lambda l: bool(re.match(r"id \d+ group", l)) or ("nhid" in l and "proto bgp" in l))
        nd = after(leaf, lambda l: l.startswith(f"169.254.0.1 dev {port} lladdr"))
        bgp_fib = after(leaf, lambda l: "via inet6" in l and f"dev {port}" in l and "proto bgp" in l)
        bfd = poll_first(leaf, lambda s: s["bfd"].get(port) == "up")
        est = poll_first(leaf, lambda s: (s["bgp"].get(port) or [None])[0] == "Established")
        pfx = poll_first(leaf, lambda s: (s["bgp"].get(port) or [None, 0])[1])
        lines.append(f"  {leaf}: ECMP group re-includes spine1 +{rel(min(group)) if group else None}; "
                     f"ND for spine1 LL +{rel(min(nd)) if nd else None}; BFD up +{rel(bfd)}; "
                     f"BGP Established +{rel(est)}; first prefix from spine1 +{rel(pfx)}; "
                     f"first BGP route via spine1 in FIB +{rel(min(bgp_fib)) if bgp_fib else None}")
    for label, ping in run["pings"].items():
        stamps = ping.get("reply_stamps", [])
        restore_gaps = [(rel(a), rel(b)) for a, b in zip(stamps, stamps[1:]) if b >= restore and b - a > GAP]
        fault_gaps = [round(b - a, 2) for a, b in zip(stamps, stamps[1:]) if restore - 10.5 <= b < restore and b - a > GAP]
        lines.append(f"    {label}: restore gaps {restore_gaps}  fault gaps {fault_gaps}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label")
    args = parser.parse_args()
    for run in json.loads(RESULT_PATH.read_text())["runs"]:
        if args.label is None or run.get("label") == args.label:
            print("\n".join(report(run)))


if __name__ == "__main__":
    main()
