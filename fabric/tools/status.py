"""One-screen status of the EMULATED fabric lab and its helpers. Works with the lab up or down.

Shows: lab nodes running vs the rendered topology; per router BGP sessions Established and BFD peers
up; shaping (TBF on leaf<->spine ports, pin rules) and the leaves' ECMP hash policy; telemetry
(exporter, Prometheus, and stray exporters not started by `make telemetry-up`, e.g. from a deleted
worktree); Batfish. Read-only.

Usage: python -m fabric.tools.status   (make fabric-status)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from fabric.batfish import service as batfish
from fabric.intent.schema.validate import load_intent
from fabric.telemetry import service as telemetry
from fabric.tests.lab import lab_nodes, node_json, node_result
from fabric.tools import shaping

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY = ROOT / "fabric" / "build" / "topology.clab.yml"
HASH_POLICY = {"0": "L3", "1": "L4"}


def expected_nodes() -> list[str]:
    if not TOPOLOGY.exists():
        return []
    return sorted(yaml.safe_load(TOPOLOGY.read_text())["topology"]["nodes"])


def routing(intent: dict) -> list[str]:
    lines = []
    for node in (n["name"] for n in intent["nodes"]):
        try:
            peers = node_json(node, 'vtysh -c "show bgp summary json"')["ipv4Unicast"]["peers"]
            bfd = node_json(node, 'vtysh -c "show bfd peers json"')
        except (AssertionError, KeyError) as error:
            lines.append(f"  {node}: cannot read BGP/BFD ({str(error).splitlines()[0][:80]})")
            continue
        established = sum(p.get("state") == "Established" for p in peers.values())
        bfd_up = sum(p.get("status") == "up" for p in bfd)
        flag = "" if established == len(peers) and bfd_up == len(bfd) else "   <-- not fully up"
        lines.append(f"  {node}: BGP {established}/{len(peers)} Established, BFD {bfd_up}/{len(bfd)} up{flag}")
    return lines


def hash_policy(intent: dict) -> str:
    seen = {}
    for leaf in (n["name"] for n in intent["nodes"] if n["role"] == "leaf"):
        try:
            value = node_result(leaf, "sysctl -n net.ipv4.fib_multipath_hash_policy")["stdout"].strip()
        except AssertionError:
            value = "?"
        seen[leaf] = HASH_POLICY.get(value, value)
    return ", ".join(f"{leaf} {policy}" for leaf, policy in seen.items())


def telemetry_lines() -> list[str]:
    pid = telemetry.read_exporter_pid()
    alive = pid is not None and telemetry.process_is_exporter(pid)
    try:
        prom = telemetry.prometheus_container()
        prom_state = "absent" if prom is None else ("running" if prom.get("State", {}).get("Running") else "stopped")
    except RuntimeError as error:
        prom_state = f"unknown ({error})"
    lines = [f"  exporter: {'running, PID ' + str(pid) if alive else 'not running'} ({telemetry.EXPORTER_METRIC_URL})",
             f"  prometheus container {telemetry.PROM_CONTAINER}: {prom_state}"]
    found = subprocess.run(["pgrep", "-af", "fabric.telemetry.exporter"], capture_output=True, text=True).stdout
    for line in found.splitlines():
        other, _, command = line.partition(" ")
        if "pgrep" not in command and (not alive or int(other) != pid):
            lines.append(f"  STRAY exporter PID {other}: {command[:110]}  (not managed by make telemetry-down; kill it)")
    return lines


def main() -> None:
    intent = load_intent()
    running = lab_nodes(intent["name"])
    expected = expected_nodes()
    print(f"EMULATED fabric lab '{intent['name']}' (containerlab, rootful podman)")
    if not running:
        print(f"  lab: NOT RUNNING (rendered topology has {len(expected)} nodes) -> make fabric-up")
    else:
        up = [n for n, state in running.items() if state == "running"]
        missing = sorted(set(expected) - set(running))
        print(f"  lab: {len(up)}/{len(expected) or len(running)} nodes running"
              + (f"; missing {', '.join(missing)}" if missing else "")
              + (f"; not running: {', '.join(n for n in running if n not in up)}" if len(up) != len(running) else ""))
        print("routing:")
        for line in routing(intent):
            print(line)
        try:
            shaped = shaping.status(intent)
            print(f"shaping: {len(shaped['shaped_ports'])}/{shaped['fabric_ports']} leaf-spine ports TBF "
                  f"{shaped['intended_rate']} ({'fully shaped' if shaped['fully_shaped'] else 'NOT fully shaped -> make fabric-shape-on'}); "
                  f"pin rules {shaped['pin_rules']}")
        except AssertionError as error:
            print(f"shaping: cannot read ({str(error).splitlines()[0][:80]})")
        print(f"ECMP hash policy: {hash_policy(intent)}")
    print("telemetry:")
    for line in telemetry_lines():
        print(line)
    print(f"batfish container {batfish.NAME}: {'running' if batfish.running() else 'not running'}")


if __name__ == "__main__":
    main()
