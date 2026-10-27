"""E8: restore and flap fixes (EMULATED, shaped uplinks).

Builds on E6 (`e6_drills`) and the #32 restore timeline (`e6_restore`):

- `audit`: timer / DAD / nexthop-object audit, no traffic; raw command output
  to e8/raw/t1-audit.txt.
- `restore --label L`: the #32 instrumented spine-loss restore (e6_restore.run),
  results appended to e8-restore-results.json; `--knob` applies a test knob
  before the runs and reverts it after.
- `flap --label L`: the E6 flap (spine1:eth1 down/up every 2 s for 20 s) with
  the measurement window extended so the step completes, plus TCP counters,
  `ss -ti` samples and uplink counters; results in e8-flap-results.json.

Usage: python -m fabric.experiments.e8 audit|restore|flap [--repeats N] [--label L] [--knob K]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.tests.lab import node_result

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "fabric" / "experiments" / "e8" / "raw"

AUDIT = {
    "spine1": [
        "vtysh -c 'show running-config'",
        "vtysh -c 'show bgp neighbors json'",
        "vtysh -c 'show bgp ipv4 unicast update-groups'",
        "vtysh -c 'show zebra'",
        "vtysh -c 'show nexthop-group rib'",
        "sh -c 'for i in eth1 eth2 eth3 eth4; do for k in accept_dad dad_transmits router_solicitation_delay optimistic_dad "
        "use_optimistic; do echo net.ipv6.conf.$i.$k=$(cat /proc/sys/net/ipv6/conf/$i/$k); done; "
        "echo net.ipv6.neigh.$i.retrans_time_ms=$(cat /proc/sys/net/ipv6/neigh/$i/retrans_time_ms); done'",
        "sh -c 'for k in fib_multipath_use_neigh fib_multipath_hash_policy; do echo net.ipv4.$k=$(cat /proc/sys/net/ipv4/$k); done'",
    ],
}
for _leaf in ("leaf1", "leaf3"):
    AUDIT[_leaf] = [
        "vtysh -c 'show running-config'",
        "vtysh -c 'show bgp neighbors json'",
        "vtysh -c 'show zebra'",
        "vtysh -c 'show nexthop-group rib'",
        "vtysh -c 'show bgp ipv4 unicast update-groups'",
        "ip nexthop show",
        # a remote prefix on the same rail (leaf2 rail A / leaf4 rail B)
        "ip route show 10.210.1.8/30" if _leaf == "leaf3" else "ip route show 10.210.0.8/30",
        "ip -4 route show proto bgp",
        "sh -c 'for k in fib_multipath_use_neigh fib_multipath_hash_policy; do echo net.ipv4.$k=$(cat /proc/sys/net/ipv4/$k); done'",
        "sh -c 'for i in eth1 eth2; do for k in accept_dad dad_transmits; do "
        "echo net.ipv6.conf.$i.$k=$(cat /proc/sys/net/ipv6/conf/$i/$k); done; done'",
    ]


def run_raw(node: str, command: str) -> str:
    try:
        result = node_result(node, command)
        out = result["stdout"]
        return out if isinstance(out, str) else json.dumps(out)
    except AssertionError as error:  # a failed command is a result
        return f"[command failed]\n{error}"


def audit() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    lines = [f"# E8 Task 1 audit {datetime.now(timezone.utc).isoformat()} (EMULATED, no traffic)"]
    for node, commands in AUDIT.items():
        for command in commands:
            lines += [f"\n$ [{node}] {command}", run_raw(node, command).rstrip()]
    (RAW / "t1-audit.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(RAW / "t1-audit.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["audit"])
    args = parser.parse_args()
    if args.what == "audit":
        audit()


if __name__ == "__main__":
    main()
