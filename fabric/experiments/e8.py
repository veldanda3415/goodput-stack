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
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.experiments import e6_drills, e6_restore
from fabric.experiments.e5_shaped import install_sync, refuse_probes, set_routing
from fabric.intent.schema.validate import load_intent
from fabric.render.shaping import rail_hosts
from fabric.tests.lab import node_result
from fabric.tools import shaping

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "fabric" / "experiments" / "e8" / "raw"
RESTORE_PATH = ROOT / "fabric" / "experiments" / "e8-restore-results.json"
LEAVES = ("leaf1", "leaf2", "leaf3", "leaf4")
SPINE_PORTS = ("eth1", "eth2", "eth3", "eth4")

# Test knobs: name -> (apply, revert), each a list of (node, command). Every
# knob is reverted after its runs, and the revert is checked by make fabric-test.
KNOBS: dict[str, tuple[list[tuple[str, str]], list[tuple[str, str]]]] = {}

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


DEBUG_ON = ("vtysh -c 'configure terminal' -c 'log file /tmp/frr-e8.log debugging' -c 'debug zebra events' "
            "-c 'debug zebra nexthop detail' -c 'debug zebra rib' -c 'debug zebra kernel'")
DEBUG_OFF = ("vtysh -c 'configure terminal' -c 'no debug zebra events' -c 'no debug zebra nexthop detail' "
             "-c 'no debug zebra rib' -c 'no debug zebra kernel' -c 'no log file'")
SNAPSHOT = ("ip nexthop show", "ip route show 10.210.1.8/30", "ip -4 route show proto bgp",
            "vtysh -c 'show nexthop-group rib'", "vtysh -c 'show ip route 10.210.1.8/30'",
            "vtysh -c 'show bgp ipv4 unicast 10.210.1.8/30'", "vtysh -c 'show interface brief'")


def mechanism(leaf: str = "leaf3", down_seconds: float = 5.0, watch_seconds: int = 12) -> None:
    """3a: what puts spine1 back in the leaf's ECMP group at link-up (no traffic)."""
    from fabric.experiments.e3.run import background, finish
    ports = " ".join(SPINE_PORTS)
    lines = [f"# E8 3a mechanism on {leaf} {datetime.now(timezone.utc).isoformat()} (EMULATED, no traffic)"]
    lines += [f"\n$ [{leaf}] {DEBUG_ON}", run_raw(leaf, DEBUG_ON).rstrip()]
    run_raw(leaf, "sh -c ': > /tmp/frr-e8.log'")
    lines += ["\n## spine1 UP (before)"] + [f"\n$ [{leaf}] {c}\n{run_raw(leaf, c).rstrip()}" for c in SNAPSHOT[:4]]
    down_t = time.time()
    lines += [f"\n## {down_t:.3f} spine1: links down", run_raw("spine1", f"sh -c 'for i in {ports}; do ip link set $i down; done'")]
    time.sleep(down_seconds)
    lines += ["\n## spine1 DOWN (after %.0f s)" % down_seconds] + [f"\n$ [{leaf}] {c}\n{run_raw(leaf, c).rstrip()}" for c in SNAPSHOT]
    monitors = {
        "ip -ts monitor nexthop route link": background(leaf, f"timeout {watch_seconds} ip -ts monitor nexthop route link"),
        "ip -6 -ts monitor neigh": background(leaf, f"timeout {watch_seconds} ip -6 -ts monitor neigh"),
    }
    time.sleep(1.0)
    up_t = time.time()
    lines += [f"\n## {up_t:.3f} ({datetime.fromtimestamp(up_t, timezone.utc).isoformat()}) spine1: links up",
              run_raw("spine1", f"sh -c 'for i in {ports}; do ip link set $i up; done'")]
    for name, proc in monitors.items():
        try:
            out = finish(leaf, proc, timeout=watch_seconds + 30)
        except RuntimeError as error:  # timeout exits 124: keep what it printed
            out = str(error)
        lines += [f"\n$ [{leaf}] {name}  (started {up_t - 1:.3f})", out.rstrip()]
    lines += ["\n## spine1 UP again (after the watch)"] + [f"\n$ [{leaf}] {c}\n{run_raw(leaf, c).rstrip()}" for c in SNAPSHOT[:4]]
    lines += [f"\n$ [{leaf}] cat /tmp/frr-e8.log", run_raw(leaf, "cat /tmp/frr-e8.log").rstrip()]
    lines += [f"\n$ [{leaf}] {DEBUG_OFF}", run_raw(leaf, DEBUG_OFF).rstrip(), run_raw(leaf, "rm -f /tmp/frr-e8.log")]
    out_path = RAW / "t3a-mechanism.txt"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_path, "restore at", up_t)


def apply_commands(commands: list[tuple[str, str]]) -> list[dict[str, Any]]:
    out = []
    for node, command in commands:
        out.append({"node": node, "command": command, "t": time.time(), "output": run_raw(node, command)[-600:]})
    return out


def load(path: Path, method: str) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {"label": "EMULATED (veth + Linux forwarding + FRR 10.2.1), SHAPED 500 Mbit/s uplinks",
            "started_at": datetime.now(timezone.utc).isoformat(), "method": method, "runs": []}


def restore(label: str, knob: str | None, repeats: int, settle: float) -> None:
    """#32 restore drill (e6_restore.run) x repeats, optional knob applied first and reverted after."""
    refuse_probes()
    intent = load_intent()
    if not shaping.status(intent)["fully_shaped"]:
        raise RuntimeError("runs with the shaped profile; run make fabric-shape-on")
    e6_drills.parse_ping = e6_restore.parse_ping_full
    install_sync([h["name"] for h in rail_hosts(intent, "A")])
    e6_restore.install_poller()
    results = load(RESTORE_PATH, "e6_restore.run (spine1 eth1-eth4 down T0+10 s, up T0+20 s) via e8 restore")
    knob_log: dict[str, Any] = {"knob": knob}
    if knob:
        knob_log["apply"] = apply_commands(KNOBS[knob][0])
        knob_log["converge_after_apply"] = e6_drills.converged(intent)
        time.sleep(settle)
    set_routing(intent, "L4", "ring")
    run_no = 800 + len(results["runs"])
    try:
        for repeat in range(1, repeats + 1):
            run_no += 1
            record = e6_restore.run(intent, run_no)
            record.update(label=label, repeat=repeat, knob=knob)
            record["reconverge_wait_seconds"] = e6_drills.converged(intent)
            results["runs"].append(record)
            RESTORE_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({"label": label, "repeat": repeat, "run": run_no,
                              **timeline(record), "reconverge_wait": round(record["reconverge_wait_seconds"], 1)}), flush=True)
            time.sleep(settle)
    finally:
        set_routing(intent, "L3", "ring")
        if knob:
            knob_log["revert"] = apply_commands(KNOBS[knob][1])
            knob_log["converge_after_revert"] = e6_drills.converged(intent)
        results.setdefault("knob_log", []).append({"label": label, **knob_log})
        RESTORE_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")


def timeline(run: dict[str, Any]) -> dict[str, Any]:
    """The Build 10 timeline columns, seconds after the restore command."""
    restore_t = next(e["t"] for e in run["events"] if e["event"] == "restore")
    inject_t = next(e["t"] for e in run["events"] if e["event"] == "inject")
    monitor = run["monitor_full"]
    port = e6_restore.SPINE1_PORT_ON_LEAF

    def rel(t: float | None) -> float | None:
        return None if t is None else round(t - restore_t, 2)

    def after(node: str, test) -> list[float]:
        return [e["t"] for e in monitor.get(node, []) if "t" in e and e["t"] >= restore_t and test(e["line"])]

    def poll_first(node: str, test) -> float | None:
        return next((s["t"] for s in run["poll"].get(node, []) if "t" in s and s["t"] >= restore_t and test(s)), None)

    def first(values: list[float]) -> float | None:
        return rel(min(values)) if values else None

    up = after("spine1", lambda l: "state UP" in l and ": eth" in l)
    dad = after("spine1", lambda l: l.startswith("local fe80"))
    fib = after("spine1", lambda l: "proto bgp" in l and "nhid" in l)
    row: dict[str, Any] = {"links_up": first(up), "dad": [first(dad), rel(max(dad)) if dad else None],
                           "spine_fib": [first(fib), rel(max(fib)) if fib else None], "group": {}, "nd": {},
                           "bfd": {}, "est": {}, "leaf_bgp_fib": {}}
    for leaf in LEAVES:
        row["group"][leaf] = first(after(leaf, lambda l: bool(re.match(r"id \d+ group", l)) or ("nhid" in l and "proto bgp" in l)))
        row["nd"][leaf] = first(after(leaf, lambda l: l.startswith(f"169.254.0.1 dev {port} lladdr")))
        row["bfd"][leaf] = rel(poll_first(leaf, lambda s: s["bfd"].get(port) == "up"))
        row["est"][leaf] = rel(poll_first(leaf, lambda s: (s["bgp"].get(port) or [None])[0] == "Established"))
        row["leaf_bgp_fib"][leaf] = first(after(leaf, lambda l: "via inet6" in l and f"dev {port}" in l and "proto bgp" in l))
    first_pfx = [s["t"] for s in run["poll"].get("spine1", []) if "t" in s and s["t"] >= restore_t
                 and any((v or [None, 0])[1] for k, v in s["bgp"].items() if k in SPINE_PORTS)]
    full_pfx = [s["t"] for s in run["poll"].get("spine1", []) if "t" in s and s["t"] >= restore_t
                and all((s["bgp"].get(k) or [None, 0])[0] == "Established" and (s["bgp"].get(k) or [None, 0])[1]
                        for k in SPINE_PORTS)]
    row["spine_pfx"] = [first(first_pfx), first(full_pfx)]
    row["loss_restore"], row["loss_fault"] = {}, {}
    for label, ping in run["pings"].items():
        stamps = ping.get("reply_stamps", [])
        short = label.split(" (")[0]
        gaps = [(rel(a), rel(b)) for a, b in zip(stamps, stamps[1:]) if b >= restore_t and b - a > e6_restore.GAP]
        fault = [(round(a - inject_t, 2), round(b - inject_t, 2)) for a, b in zip(stamps, stamps[1:])
                 if inject_t - 0.5 <= b < restore_t and b - a > e6_restore.GAP]
        if gaps:
            row["loss_restore"][short] = gaps
        if fault:
            row["loss_fault"][short] = fault
    return row


def fmt_restore(label: str | None = None) -> str:
    runs = [r for r in json.loads(RESTORE_PATH.read_text())["runs"] if label is None or r.get("label") == label]
    rows = [(r, timeline(r)) for r in runs]

    def leaves(d: dict[str, Any]) -> str:
        return " / ".join("—" if d[l] is None else f"{d[l]:.2f}" for l in LEAVES)

    def pair(p: list[Any]) -> str:
        return " / ".join("—" if v is None else f"{v:.2f}" for v in p)

    def loss(d: dict[str, Any]) -> str:
        return "; ".join(f"{k} " + ", ".join(f"{a:.2f}→{b:.2f}" for a, b in v) for k, v in d.items()) or "none"

    head = "| | " + " | ".join(f"run {r['run']}" for r, _ in rows) + " |"
    lines = [head, "|---" * (len(rows) + 1) + "|"]
    spec = [
        ("spine1 links up", lambda t: f"+{t['links_up']:.2f}" if t["links_up"] is not None else "—"),
        ("leaf1–4: group re-includes spine1", lambda t: leaves(t["group"])),
        ("spine1 link-local DAD done (first / last)", lambda t: pair(t["dad"])),
        ("leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4)", lambda t: leaves(t["nd"])),
        ("BFD up (leaf1 / 2 / 3 / 4)", lambda t: leaves(t["bfd"])),
        ("BGP Established (leaf1 / 2 / 3 / 4)", lambda t: leaves(t["est"])),
        ("spine1 first / full prefixes received", lambda t: pair(t["spine_pfx"])),
        ("spine1 kernel FIB: first / last BGP route", lambda t: pair(t["spine_fib"])),
        ("leaf first BGP route via spine1 in FIB (leaf1 / 2 / 3 / 4)", lambda t: leaves(t["leaf_bgp_fib"])),
        ("probe loss after restore (last reply → next reply)", lambda t: loss(t["loss_restore"])),
        ("loss at the failure (s after inject)", lambda t: loss(t["loss_fault"])),
        ("wait to all-up after the run, s", None),
    ]
    for name, fn in spec:
        if fn is None:
            cells = [f"{r['reconverge_wait_seconds']:.1f}" for r, _ in rows]
        else:
            cells = [fn(t) for _, t in rows]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["audit", "mechanism", "restore", "restore-report"])
    parser.add_argument("--label")
    parser.add_argument("--knob", choices=sorted(KNOBS) or None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--settle", type=float, default=15.0)
    args = parser.parse_args()
    if args.what == "audit":
        audit()
    elif args.what == "mechanism":
        mechanism()
    elif args.what == "restore":
        restore(args.label or "baseline", args.knob, args.repeats, args.settle)
    elif args.what == "restore-report":
        print(fmt_restore(args.label))


if __name__ == "__main__":
    main()
