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
import base64
import json
import threading
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
# A no-traffic spine1 down/up cycle after a zebra knob change, so every route is
# reinstalled under the knob before the measured runs (zebra applies it per install).
SPINE1_CYCLE = ("spine1", "sh -c 'for i in eth1 eth2 eth3 eth4; do ip link set $i down; done; sleep 3; "
                "for i in eth1 eth2 eth3 eth4; do ip link set $i up; done'")
KNOBS: dict[str, tuple[list[tuple[str, str]], list[tuple[str, str]]]] = {
    "no-kernel-nhg": (
        [(leaf, "vtysh -c 'configure terminal' -c 'no zebra nexthop kernel enable'") for leaf in LEAVES] + [SPINE1_CYCLE],
        [(leaf, "vtysh -c 'configure terminal' -c 'zebra nexthop kernel enable'") for leaf in LEAVES] + [SPINE1_CYCLE],
    ),
}

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


def mechanism(leaf: str = "leaf3", down_seconds: float = 5.0, watch_seconds: int = 12, out_name: str = "t3a-mechanism.txt") -> None:
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
    out_path = RAW / out_name
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_path, "restore at", up_t)


FLAP_PATH = ROOT / "fabric" / "experiments" / "e8-flap-results.json"
FLAP_DURATION = 60  # E6 used 30 s and the flap step had not completed; 60 s lets it finish
SENDERS = ("host1", "host2", "host3", "host4")
# leaf -> host-facing iif for the ring senders behind it (intent links host*-leaf1/leaf2, rail A)
SENDER_IIF = {"leaf1": {"host1": "eth3", "host2": "eth4"}, "leaf2": {"host3": "eth3", "host4": "eth4"}}

NSTAT_LOOP = ("sh -c 'end=$(( $(date +%s) + {n} )); while [ $(date +%s) -lt $end ]; do echo T $(date +%s.%N); "
              "nstat -asz TcpRetransSegs TcpExtTCPTimeouts TcpExtTCPLossProbes TcpExtTCPSpuriousRTOs TcpOutSegs "
              "| tail -n +2; sleep 0.5; done'")
SS_LOOP = ("sh -c 'end=$(( $(date +%s) + {n} )); while [ $(date +%s) -lt $end ]; do echo T $(date +%s.%N); "
           "ss -tin state established \\( dport \\>= :8100 and dport \\< :8600 \\); sleep 1; done'")
UPLINK_POLL = r'''
import sys, time
end = time.time() + float(sys.argv[1])
while time.time() < end:
    t = time.time()
    row = [f"{t:.3f}"]
    for dev in ("eth1", "eth2"):
        for k in ("tx_bytes", "rx_bytes"):
            try:
                row.append(open(f"/sys/class/net/{dev}/statistics/{k}").read().strip())
            except OSError:
                row.append("nan")
    print(" ".join(row), flush=True)
    time.sleep(max(0.0, 0.1 - (time.time() - t)))
'''

# EMULATED-POLICY link-flap hold-down on spine1:eth1, standing in for a NOS
# link-flap error-disable with automatic recovery (e.g. Cisco "errdisable detect
# cause link-flap" + "errdisable recovery", Arista "errdisable flap-setting cause
# link-flap"). Policy (E8 §4b): on the 2nd carrier-down within WINDOW s, set the
# port admin-down; re-enable once HOLD s have passed with no new flap. While the
# port is admin-down the far end is not observable (veth, like a laser that is
# off), so a hold ends HOLD s after it starts and a down within WINDOW s of the
# previous one starts the next hold.
HOLDDOWN = r'''
import json, subprocess, sys, time
dev, run_for, window, hold = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
end = time.time() + run_for
def oper():
    try:
        return open(f"/sys/class/net/{dev}/operstate").read().strip()
    except OSError:
        return "?"
def log(**kw):
    print(json.dumps({"t": time.time(), **kw}), flush=True)
downs, last = [], oper()
log(event="start", oper=last)
while time.time() < end:
    now, state = time.time(), oper()
    if state != last:
        log(event="oper", oper=state)
        if last == "up" and state != "up":
            downs = [d for d in downs if now - d <= window] + [now]
            if len(downs) >= 2:
                subprocess.run(["ip", "link", "set", dev, "down"])
                log(event="hold_start", downs_in_window=len(downs))
                time.sleep(hold)
                subprocess.run(["ip", "link", "set", dev, "up"])
                log(event="hold_end")
                state = oper()
                log(event="oper", oper=state)
        last = state
    time.sleep(0.01)
log(event="stop", oper=oper())
'''


def fault_flap_leafside():
    """E6 flap pattern (down 2 s / up 2 s x5 from T0+5 s) driven from leaf1:eth1, the far end of spine1:eth1."""
    from fabric.experiments.e3.run import background, finish
    meta = {"link": "spine1:eth1 <-> leaf1:eth1", "how": "leaf1 ip link set eth1 down 2 s / up 2 s, 5 cycles from T0+5 s",
            "inject_at": 5.0, "restore_at": 25.0}
    holder: dict[str, Any] = {}

    def inject():
        holder["p"] = background(
            "leaf1", "sh -c 'for i in 1 2 3 4 5; do ip link set eth1 down; sleep 2; ip link set eth1 up; sleep 2; done'")
        return [{"node": "leaf1", "command": "flap loop start", "t": time.time(), "rc": 0}]

    def restore():
        finish("leaf1", holder["p"], timeout=40)
        return [e6_drills.sh("leaf1", "ip link set eth1 up")]
    return inject, restore, meta


def flow_placement() -> dict[str, Any]:
    """Which uplink each ring flow hashes to on its source leaf (L4 hash, both uplinks up)."""
    out: dict[str, Any] = {}
    for leaf, iifs in SENDER_IIF.items():
        for host, iif in iifs.items():
            sockets = run_raw(host, "ss -tnH state established '( dport >= :8100 and dport < :8600 )'")
            flows = []
            for line in sockets.splitlines():
                parts = line.split()
                if len(parts) < 4:
                    continue
                src, dst = parts[-2].rsplit(":", 1), parts[-1].rsplit(":", 1)
                cmd = (f"ip route get {dst[0]} from {src[0]} iif {iif} ipproto tcp sport {src[1]} dport {dst[1]}")
                flows.append({"src": src[0], "sport": int(src[1]), "dst": dst[0], "dport": int(dst[1]), "cmd": cmd})
            if flows:
                script = "; ".join(f["cmd"] for f in flows)
                answers = [l for l in run_raw(leaf, f"sh -c '{script}'").splitlines() if " dev " in l]
                for flow, answer in zip(flows, answers):
                    flow["dev"] = answer.split(" dev ")[1].split()[0]
                    flow["route"] = answer.strip()
            out[host] = {"leaf": leaf, "iif": iif, "flows": flows,
                         "per_uplink": {d: sum(1 for f in flows if f.get("dev") == d) for d in ("eth1", "eth2")}}
    return out


def flap(label: str, repeats: int, settle: float, injector: str, holddown: bool) -> None:
    from fabric.experiments.e3.run import background
    refuse_probes()
    intent = load_intent()
    if not shaping.status(intent)["fully_shaped"]:
        raise RuntimeError("runs with the shaped profile; run make fabric-shape-on")
    install_sync([h["name"] for h in rail_hosts(intent, "A")])
    for node, name, body in (("leaf1", "/tmp/e8_uplinks.py", UPLINK_POLL), ("leaf2", "/tmp/e8_uplinks.py", UPLINK_POLL),
                             ("spine1", "/tmp/e8_holddown.py", HOLDDOWN)):
        blob = base64.b64encode(body.encode()).decode()
        run_raw(node, f"sh -c 'echo {blob} | base64 -d > {name}'")
    results = load(FLAP_PATH, "e6_drills.run_once flap with a longer window via e8 flap")
    set_routing(intent, "L4", "ring")
    run_no = 850 + len(results["runs"])
    span = FLAP_DURATION + 12
    try:
        for repeat in range(1, repeats + 1):
            run_no += 1
            procs = {f"nstat:{h}": background(h, NSTAT_LOOP.format(n=span)) for h in SENDERS}
            procs["ss:host1"] = background("host1", SS_LOOP.format(n=span))
            procs.update({f"uplinks:{l}": background(l, f"python3 /tmp/e8_uplinks.py {span}") for l in ("leaf1", "leaf2")})
            if holddown:
                procs["holddown:spine1"] = background("spine1", f"python3 /tmp/e8_holddown.py eth1 {span} 10 5")
            placement: dict[str, Any] = {}
            timer = threading.Timer(7.0, lambda: placement.update(flow_placement()))
            timer.start()
            if injector == "none":
                fault = None
            else:
                fault = e6_drills.fault_flap() if injector == "spine1" else fault_flap_leafside()
            record = e6_drills.run_once(intent, "flap" if fault else "baseline", fault, run_no, FLAP_DURATION)
            timer.join()
            record["samplers"] = {}
            for name, proc in procs.items():
                node = name.split(":")[1]
                try:
                    stdout, _ = proc.communicate(timeout=span + 60)
                    res = json.loads(stdout)[f"clab-{intent['name']}-{node}"][0]["stdout"]
                    record["samplers"][name] = res if isinstance(res, str) else json.dumps(res)
                except Exception as error:  # noqa: BLE001 - a failed sampler is a result
                    record["samplers"][name] = f"[sampler failed] {error}"[-400:]
            record.update(label=label, repeat=repeat, injector=injector, holddown=holddown, placement=placement)
            record["reconverge_wait_seconds"] = e6_drills.converged(intent)
            results["runs"].append(record)
            FLAP_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({"label": label, "repeat": repeat, "run": run_no, **flap_summary(record)}), flush=True)
            time.sleep(settle)
    finally:
        set_routing(intent, "L3", "ring")
        run_raw("spine1", "ip link set eth1 up")
        run_raw("leaf1", "ip link set eth1 up")
        FLAP_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")


def flap_summary(run: dict[str, Any]) -> dict[str, Any]:
    from fabric.experiments import e6_report
    target = e6_report.summarize()["target_bytes"]  # E6's W (baseline slowest pair at T0+20 s)
    step = e6_report.step_time(run, target)
    reached = min(e6_report.cumulative(p)[-1][1] for p in run["pairs"] if "timeline" in p) / target
    stall, stalled, streams = e6_report.stream_stall(run)
    return {"step": None if step is None else round(step, 2), "reached_W": round(reached, 3),
            "stall_s": stall, "streams_stalled_1s": stalled, "streams": streams,
            "tcp": tcp_counters(run), "placement": {h: v["per_uplink"] for h, v in run.get("placement", {}).items()},
            "holddown": holddown_events(run)}


def tcp_counters(run: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Per sender: counter deltas over the run (first to last nstat sample)."""
    out = {}
    for name, text in run.get("samplers", {}).items():
        if not name.startswith("nstat:"):
            continue
        samples, cur = [], None
        for line in text.splitlines():
            if line.startswith("T "):
                cur = {"t": float(line.split()[1])}
                samples.append(cur)
            elif cur is not None and line.split() and line.split()[0].startswith("Tcp"):
                cur[line.split()[0]] = int(line.split()[1])
        full = [s for s in samples if "TcpRetransSegs" in s]
        if len(full) >= 2:
            out[name.split(":")[1]] = {k: full[-1][k] - full[0][k] for k in full[0] if k != "t"}
    return out


def holddown_events(run: dict[str, Any]) -> list[dict[str, Any]]:
    text = run.get("samplers", {}).get("holddown:spine1", "")
    return [json.loads(l) for l in text.splitlines() if l.startswith("{")]


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
        # 10 Hz poller: kernel BGP routes (other than spine1's own loopback) via the spine1 port;
        # works for nexthop-group and inline multipath routes alike
        row.setdefault("leaf_uses_spine1", {})[leaf] = rel(poll_first(
            leaf, lambda s: any(p != "10.200.0.1" for p in s["fib"].get(port, []))))
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
        ("leaf kernel routes to remote prefixes use spine1 (poller, leaf1 / 2 / 3 / 4)", lambda t: leaves(t["leaf_uses_spine1"])),
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
    parser.add_argument("what", choices=["audit", "mechanism", "restore", "restore-report", "flap"])
    parser.add_argument("--label")
    parser.add_argument("--knob", choices=sorted(KNOBS) or None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--settle", type=float, default=15.0)
    parser.add_argument("--injector", choices=["spine1", "leaf1", "none"], default="spine1", help="flap: which end toggles eth1 (none = no fault)")
    parser.add_argument("--holddown", action="store_true", help="flap: run the EMULATED-POLICY hold-down on spine1:eth1")
    parser.add_argument("--out", help="mechanism: raw output file name under e8/raw/")
    args = parser.parse_args()
    if args.what == "audit":
        audit()
    elif args.what == "mechanism":
        mechanism(out_name=args.out or "t3a-mechanism.txt")
    elif args.what == "restore":
        restore(args.label or "baseline", args.knob, args.repeats, args.settle)
    elif args.what == "flap":
        flap(args.label or "baseline-flap", args.repeats, args.settle, args.injector, args.holddown)
    elif args.what == "restore-report":
        print(fmt_restore(args.label))


if __name__ == "__main__":
    main()
