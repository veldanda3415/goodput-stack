"""E6 restore transient (#32): instrumented spine-loss drill (EMULATED, shaped uplinks).

Reruns the E6 spine-loss drill (all spine1 fabric links down at T0+10 s, up
at T0+20 s, ring load + ping probes from e6_drills.run_once) and adds, on one
clock, what happens on restore:

- `ip -ts monitor link route nexthop neigh` on spine1 and leaf1..4 (kernel
  event times; containers print UTC wall clock without an offset, parsed as UTC);
- a 10 Hz poller inside spine1 and leaf1..4 (python3 `time.time()`; the
  containers share the host kernel clock): BGP session state + pfxRcd per
  peer, BFD status per peer, and the kernel's BGP routes split by next-hop
  device (`ip -4 route show proto bgp`);
- every ping reply timestamp (`ping -D`), so loss windows are exact gaps.

Usage: python -m fabric.experiments.e6_restore [--repeats N] [--label before|after]
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.experiments import e6_drills
from fabric.experiments.e3.run import background
from fabric.experiments.e5_shaped import install_sync, refuse_probes, set_routing
from fabric.intent.schema.validate import load_intent
from fabric.render.shaping import rail_hosts
from fabric.tools import shaping

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e6-restore-results.json"
NODES = ("spine1", "leaf1", "leaf2", "leaf3", "leaf4")
SPINE1_PORT_ON_LEAF = "eth1"  # every leaf's eth1 faces spine1
POLL_SECONDS = 44  # covers sync lead + 30 s run + tail
GAP = 0.25  # a reply gap longer than this (probe interval 0.1 s) is loss

POLLER = r'''
import json, subprocess, sys, time
end = time.time() + float(sys.argv[1])
while time.time() < end:
    t = time.time()
    raw = subprocess.run(["vtysh", "-c", "show bgp ipv4 unicast summary json", "-c", "show bfd peers brief json"],
                         capture_output=True, text=True).stdout
    dec = json.JSONDecoder(); docs = []; i = 0
    while i < len(raw):
        if raw[i].isspace(): i += 1; continue
        try:
            obj, i = dec.raw_decode(raw, i); docs.append(obj)
        except ValueError:
            break
    bgp = {}; bfd = {}
    for d in docs:
        if isinstance(d, dict) and "peers" in d:
            bgp = {k: [v.get("state"), v.get("pfxRcd")] for k, v in d["peers"].items()}
        elif isinstance(d, list):
            bfd = {p.get("interface") or p.get("peer"): p.get("status") for p in d}
    routes = subprocess.run(["ip", "-4", "route", "show", "proto", "bgp"], capture_output=True, text=True).stdout
    fib = {}
    prefix = None
    for line in routes.splitlines():
        if not line.startswith((" ", "\t")):
            prefix = line.split()[0]
        for dev in [w2 for w1, w2 in zip(line.split(), line.split()[1:]) if w1 == "dev"]:
            fib.setdefault(dev, []).append(prefix)
    print(json.dumps({"t": t, "dt": round(time.time() - t, 4), "bgp": bgp, "bfd": bfd,
                      "fib": {d: sorted(set(p)) for d, p in fib.items()}}), flush=True)
    time.sleep(max(0.0, 0.1 - (time.time() - t)))
'''


def install_poller() -> None:
    blob = base64.b64encode(POLLER.encode()).decode()
    for node in NODES:
        e6_drills.node_result(node, f"sh -c 'echo {blob} | base64 -d > /tmp/e6_poll.py'")


def parse_monitor_full(output: str) -> list[dict[str, Any]]:
    events = []
    for line in output.splitlines():
        m = re.match(r"\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)\]\s*(.*)", line)
        if m:
            when = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()
            events.append({"t": when, "line": m.group(2)[:300]})
    return events


def parse_ping_full(output: str) -> dict[str, Any]:
    summary = ORIGINAL_PARSE_PING(output)
    summary["reply_stamps"] = [float(m.group(1)) for m in re.finditer(r"^\[(\d+\.\d+)\].*bytes from", output, re.M)]
    return summary


ORIGINAL_PARSE_PING = e6_drills.parse_ping


def collect(proc, node: str, intent: dict[str, Any]) -> str:
    stdout, _ = proc.communicate(timeout=POLL_SECONDS + 60)
    out = json.loads(stdout)[f"clab-{intent['name']}-{node}"][0]["stdout"]
    return out if isinstance(out, str) else json.dumps(out)


def run(intent: dict[str, Any], run_no: int) -> dict[str, Any]:
    pollers = {n: background(n, f"python3 /tmp/e6_poll.py {POLL_SECONDS}") for n in NODES}
    monitors = {n: background(n, f"timeout {POLL_SECONDS} ip -ts monitor link route nexthop neigh") for n in NODES}
    time.sleep(0.5)
    record = e6_drills.run_once(intent, "spine-loss", e6_drills.fault_spine_loss(), run_no)
    record["poll"] = {}
    record["monitor_full"] = {}
    for node in NODES:
        try:
            record["poll"][node] = [json.loads(l) for l in collect(pollers[node], node, intent).splitlines() if l.startswith("{")]
        except Exception as error:  # noqa: BLE001 - a failed collector is a result
            record["poll"][node] = [{"error": str(error)[-300:]}]
        try:
            record["monitor_full"][node] = parse_monitor_full(collect(monitors[node], node, intent))
        except Exception as error:  # noqa: BLE001
            record["monitor_full"][node] = [{"error": str(error)[-300:]}]
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--label", default="before", help="before = current intent; after = with the restore knob")
    parser.add_argument("--settle", type=float, default=15.0, help="extra seconds after reconvergence between runs")
    args = parser.parse_args()
    refuse_probes()
    intent = load_intent()
    if not shaping.status(intent)["fully_shaped"]:
        raise RuntimeError("runs with the shaped profile; run make fabric-shape-on")
    e6_drills.parse_ping = parse_ping_full
    install_sync([h["name"] for h in rail_hosts(intent, "A")])
    install_poller()
    set_routing(intent, "L4", "ring")
    results = json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists() else {
        "label": "EMULATED (veth + Linux forwarding + FRR 10.2.1), SHAPED 500 Mbit/s uplinks",
        "started_at": datetime.now(timezone.utc).isoformat(), "method": __doc__, "runs": [],
    }
    run_no = 900 + len(results["runs"])
    try:
        for repeat in range(1, args.repeats + 1):
            run_no += 1
            record = run(intent, run_no)
            record["label"], record["repeat"] = args.label, repeat
            record["reconverge_wait_seconds"] = e6_drills.converged(intent)
            results["runs"].append(record)
            RESULT_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({"label": args.label, "repeat": repeat,
                              "poll_samples": {n: len(v) for n, v in record["poll"].items()},
                              "reconverge_wait": round(record["reconverge_wait_seconds"], 1)}), flush=True)
            time.sleep(args.settle)
    finally:
        set_routing(intent, "L3", "ring")
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        RESULT_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
