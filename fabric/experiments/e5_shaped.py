"""E5 shaped rerun: make the leaf<->spine links the bottleneck (EMULATED).

Unshaped E5 job time was dominated by serial `containerlab exec` launch
offsets (see E5 "Correction"). This runner starts every iperf3 client at one
absolute time T0 (all containers share the WSL2 kernel clock), sends a fixed
byte count per pair (`iperf3 -n`, a per-test total across `-P` streams), and
takes job time = last client exit - T0. It records per-container CPU from
cgroup v2 `cpu.stat` and TX byte deltas on both ends of every fabric link.

Subcommands:
  baseline  unshaped single-flow and aggregate host throughput + CPU
  run       ring/all-to-all x L3/L4/pinned x flows/pair, shaping must be ON
"""
from __future__ import annotations

import argparse
import base64
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.experiments.e1 import active_gateway_probes
from fabric.experiments.e3.run import background, finish
from fabric.intent.schema.validate import load_intent
from fabric.render.shaping import collective_pairs, fabric_ports, rail_hosts
from fabric.tests.lab import node_json, node_result
from fabric.tools import shaping

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e5-shaped-results.json"
BASELINE_PATH = ROOT / "fabric" / "experiments" / "e5-shaped-baseline.json"
SYNC_SCRIPT = "/tmp/e5sync.sh"
SYNC_LEAD_SECONDS = 1.5
PORT_BASE = 7000
PATTERNS = ("ring", "all-to-all")
ROUTING = ("L3", "L4", "pinned")
FLOWS = (1, 16)
REPEATS = 3
IDEAL_SECONDS = 3.0
SYNC_SH = """#!/bin/sh
t0=$1; shift
now=$(date +%s.%N)
d=$(awk -v a="$t0" -v b="$now" 'BEGIN{x=a-b; if (x<0) x=0; printf "%.6f", x}')
sleep "$d"
echo "SYNC_START $(date +%s.%N)"
"$@"
rc=$?
echo "SYNC_END $(date +%s.%N) $rc"
"""


def install_sync(hosts: list[str]) -> None:
    encoded = base64.b64encode(SYNC_SH.encode()).decode()
    for host in hosts:
        node_result(host, f"sh -c 'echo {encoded} | base64 -d > {SYNC_SCRIPT}'")


def parallel(commands: dict[str, str], timeout: int = 30) -> dict[str, str]:
    procs = {node: background(node, command) for node, command in commands.items()}
    return {node: finish(node, proc, timeout=timeout) for node, proc in procs.items()}


def cpu_snapshot(hosts: list[str]) -> dict[str, Any]:
    """Container cgroup CPU usage plus system-wide /proc/stat (shared kernel)."""
    out = parallel({h: "sh -c 'cat /sys/fs/cgroup/cpu.stat; head -1 /proc/stat'" for h in hosts})
    snap: dict[str, Any] = {"t": time.time(), "hosts": {}}
    for host, text in out.items():
        fields = dict(line.split()[:2] for line in text.splitlines() if line and not line.startswith("cpu "))
        snap["hosts"][host] = int(fields["usage_usec"])
        proc = next(line for line in text.splitlines() if line.startswith("cpu "))
        values = [int(v) for v in proc.split()[1:]]
        snap["system"] = {"idle": values[3] + values[4], "total": sum(values)}
    return snap


def cpu_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    wall = after["t"] - before["t"]
    total = after["system"]["total"] - before["system"]["total"]
    idle = after["system"]["idle"] - before["system"]["idle"]
    return {
        "wall_seconds": wall,
        "container_cpu_cores": {
            host: (after["hosts"][host] - before["hosts"][host]) / 1e6 / wall
            for host in before["hosts"]
        },
        "system_busy_percent": 100 * (total - idle) / total if total else None,
        "note": "container = cgroup v2 usage_usec / wall; system = all 16 vCPUs of the WSL2 VM",
    }


def link_snapshot(intent: dict[str, Any]) -> dict[str, dict[str, dict[str, int]]]:
    """TX bytes and qdisc drops on every fabric port (both ends of each link)."""
    snap: dict[str, dict[str, dict[str, int]]] = {}
    for node, interfaces in fabric_ports(intent).items():
        links = {link["ifname"]: link for link in node_json(node, "ip -j -s link show")}
        qdiscs = {q["dev"]: q for q in node_json(node, "tc -j -s qdisc show") if q.get("root")}
        snap[node] = {
            interface: {
                "tx_bytes": int(links[interface]["stats64"]["tx"]["bytes"]),
                "qdisc_drops": int(qdiscs.get(interface, {}).get("drops", 0)),
            }
            for interface in interfaces
        }
    return snap


def link_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, dict[str, int]]]:
    return {
        node: {
            port: {key: after[node][port][key] - value for key, value in stats.items()}
            for port, stats in ports.items()
        }
        for node, ports in before.items()
    }


def parse_sync(output: str) -> dict[str, Any]:
    lines = output.strip().splitlines()
    start = float(lines[0].split()[1])
    end_fields = lines[-1].split()
    document = json.loads("\n".join(lines[1:-1]))
    return {"start": start, "end": float(end_fields[1]), "rc": int(end_fields[2]), "iperf3": document}


def receiver_last_byte_seconds(document: dict[str, Any]) -> float | None:
    """Server-side (receiver) time at which the cumulative bytes reach the
    final received total, from 0.1 s server intervals, linearly interpolated."""
    server = document.get("server_output_json") or {}
    intervals = [i["sum"] for i in server.get("intervals", []) if "sum" in i]
    total = sum(int(i["bytes"]) for i in intervals)
    if not intervals or total == 0:
        return None
    cumulative = 0
    for interval in intervals:
        size = int(interval["bytes"])
        if cumulative + size >= total and size > 0:
            fraction = (total - cumulative) / size
            return float(interval["start"]) + fraction * (float(interval["end"]) - float(interval["start"]))
        cumulative += size
    return float(intervals[-1]["end"])


def run_cell(
    intent: dict[str, Any],
    pattern: str,
    flows: int,
    pair_bytes: int | None,
    duration: int | None,
    cell: int,
) -> dict[str, Any]:
    rail = intent["lab_shaping"]["pin_rail"]
    hosts = {h["name"]: h for h in rail_hosts(intent, rail)}
    pairs = collective_pairs(list(hosts), pattern)
    names = sorted(hosts)
    links_before = link_snapshot(intent)
    cpu_before = cpu_snapshot(names)
    servers = {}
    for index, (_, destination) in enumerate(pairs):
        port = PORT_BASE + (cell % 50) * 20 + index
        servers[(destination, port)] = background(destination, f"timeout 40 iperf3 -s -1 -i 0.1 -J -p {port}")
    time.sleep(0.6)
    t0 = time.time() + SYNC_LEAD_SECONDS
    amount = f"-n {pair_bytes}" if pair_bytes else f"-t {duration}"
    clients = []
    for index, (source, destination) in enumerate(pairs):
        port = PORT_BASE + (cell % 50) * 20 + index
        command = (
            f"sh {SYNC_SCRIPT} {t0:.6f} timeout 30 iperf3 -c {hosts[destination]['ip']} "
            f"-B {hosts[source]['ip']} -p {port} -P {flows} {amount} --get-server-output --json"
        )
        clients.append((source, destination, command, background(source, command)))
    pair_results = []
    for source, destination, command, proc in clients:
        parsed = parse_sync(finish(source, proc, timeout=60))
        end = parsed["iperf3"]["end"]
        last_byte = receiver_last_byte_seconds(parsed["iperf3"])
        pair_results.append({
            "receiver_last_byte_offset_seconds": (
                parsed["start"] - t0 + last_byte if last_byte is not None else None
            ),
            "source": source,
            "destination": destination,
            "same_leaf": hosts[source]["leaf"] == hosts[destination]["leaf"],
            "command": command,
            "start_offset_seconds": parsed["start"] - t0,
            "end_offset_seconds": parsed["end"] - t0,
            "iperf3_rc": parsed["rc"],
            "received_bytes": end["sum_received"]["bytes"],
            "received_gbps": end["sum_received"]["bits_per_second"] / 1e9,
            "iperf3_seconds": end["sum_received"]["seconds"],
            "retransmits": end["sum_sent"].get("retransmits"),
            "cpu_utilization_percent": end.get("cpu_utilization_percent"),
        })
    for (destination, _), proc in servers.items():
        finish(destination, proc, timeout=60)
    cpu = cpu_delta(cpu_before, cpu_snapshot(names))
    deltas = link_delta(links_before, link_snapshot(intent))
    tx = {f"{node}:{port}": stats["tx_bytes"] for node, ports in deltas.items() for port, stats in ports.items()}
    leaf_imbalance = {}
    for node in (n["name"] for n in intent["nodes"] if n["role"] == "leaf"):
        values = [deltas[node][p]["tx_bytes"] for p in deltas[node]]
        leaf_imbalance[node] = max(values) / statistics.mean(values) if sum(values) else None
    rate = intent["lab_shaping"]["uplink_rate_mbit"] * 1e6
    max_link = max(tx, key=tx.get)
    return {
        "pattern": pattern,
        "flows_per_pair": flows,
        "pair_bytes": pair_bytes,
        "duration_seconds": duration,
        "t0_epoch": t0,
        "start_skew_seconds": max(p["start_offset_seconds"] for p in pair_results)
        - min(p["start_offset_seconds"] for p in pair_results),
        "job_time_seconds": max(p["end_offset_seconds"] for p in pair_results),
        "receiver_job_time_seconds": max(
            (p["receiver_last_byte_offset_seconds"] for p in pair_results
             if p["receiver_last_byte_offset_seconds"] is not None), default=None
        ),
        "pairs": pair_results,
        "cpu": cpu,
        "link_deltas": deltas,
        "max_link": max_link,
        "max_link_tx_bytes": tx[max_link],
        "max_link_bound_seconds": tx[max_link] * 8 / rate,
        "leaf_uplink_imbalance": leaf_imbalance,
        "worst_leaf_imbalance": max(v for v in leaf_imbalance.values() if v is not None),
        "qdisc_drops_total": sum(s["qdisc_drops"] for ports in deltas.values() for s in ports.values()),
    }


def set_routing(intent: dict[str, Any], mode: str, pattern: str) -> None:
    leaves = [n["name"] for n in intent["nodes"] if n["role"] == "leaf"]
    policy = 1 if mode == "L4" else 0
    for leaf in leaves:
        node_result(leaf, f"sysctl -w net.ipv4.fib_multipath_hash_policy={policy}")
    shaping.apply_pins(intent, pattern if mode == "pinned" else None)


def pair_bytes_for(intent: dict[str, Any], pattern: str) -> int:
    """Bytes per pair so the even-split (pinned) job takes ~IDEAL_SECONDS.

    Ring: each leaf sources two cross-leaf pairs over two uplinks -> one pair
    per uplink at the full rate. All-to-all: four cross-leaf pairs per leaf
    -> two per uplink at half the rate each.
    """
    rate_bytes = intent["lab_shaping"]["uplink_rate_mbit"] * 1e6 / 8
    share = 1.0 if pattern == "ring" else 0.5
    return int(rate_bytes * share * IDEAL_SECONDS)


def refuse_probes() -> None:
    probes = active_gateway_probes()
    if probes:
        raise RuntimeError("gateway probe active; refusing traffic: " + "; ".join(probes))


def baseline() -> None:
    """Unshaped capacity: single flow and all-host aggregate, with CPU."""
    refuse_probes()
    intent = load_intent()
    if shaping.status(intent)["shaped_ports"]:
        raise RuntimeError("baseline must run unshaped; run make fabric-shape-off")
    names = sorted(h["name"] for h in rail_hosts(intent, intent["lab_shaping"]["pin_rail"]))
    install_sync(names)
    out: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "label": "EMULATED (veth + Linux forwarding), UNSHAPED",
        "single_flow": [],
        "aggregate": [],
    }
    hosts = {h["name"]: h for h in rail_hosts(intent, intent["lab_shaping"]["pin_rail"])}
    for repeat in range(1, 4):
        server = background("host3", f"timeout 20 iperf3 -s -1 -p {PORT_BASE + 900 + repeat}")
        time.sleep(0.5)
        command = (
            f"iperf3 -c {hosts['host3']['ip']} -B {hosts['host1']['ip']} "
            f"-p {PORT_BASE + 900 + repeat} -P 1 -t 5 --json"
        )
        document = json.loads(finish("host1", background("host1", command), timeout=30))
        finish("host3", server, timeout=30)
        out["single_flow"].append({
            "command": command,
            "received_gbps": document["end"]["sum_received"]["bits_per_second"] / 1e9,
            "retransmits": document["end"]["sum_sent"].get("retransmits"),
            "cpu_utilization_percent": document["end"].get("cpu_utilization_percent"),
        })
        print(json.dumps(out["single_flow"][-1]))
    for repeat in range(1, 4):
        for pattern in PATTERNS:
            cell = run_cell(intent, pattern, 16, None, 5, 40 + repeat * 2 + PATTERNS.index(pattern))
            per_host = {
                name: sum(p["received_gbps"] for p in cell["pairs"] if p["source"] == name)
                for name in names
            }
            cell["per_host_sent_gbps"] = per_host
            cell["repeat"] = repeat
            out["aggregate"].append(cell)
            print(json.dumps({
                "pattern": pattern, "repeat": repeat, "per_host_sent_gbps": per_host,
                "cpu": cell["cpu"]["container_cpu_cores"],
                "system_busy_percent": cell["cpu"]["system_busy_percent"],
            }))
    out["completed_at"] = datetime.now(timezone.utc).isoformat()
    BASELINE_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE_PATH}")


def run(resume: bool) -> None:
    refuse_probes()
    intent = load_intent()
    if not shaping.status(intent)["fully_shaped"]:
        raise RuntimeError("shaped rerun needs every fabric port shaped; run make fabric-shape-on")
    names = sorted(h["name"] for h in rail_hosts(intent, intent["lab_shaping"]["pin_rail"]))
    install_sync(names)
    results: dict[str, Any] = (
        json.loads(RESULT_PATH.read_text()) if resume and RESULT_PATH.exists() else {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "label": "EMULATED (veth + Linux forwarding), SHAPED leaf<->spine TBF",
            "lab_shaping": intent["lab_shaping"],
            "method": __doc__,
            "cells": [],
        }
    )
    done = {(c["pattern"], c["routing"], c["flows_per_pair"], c["repeat"]) for c in results["cells"]}
    cell_number = 0
    try:
        for pattern in PATTERNS:
            for mode in ROUTING:
                set_routing(intent, mode, pattern)
                for flows in FLOWS:
                    for repeat in range(1, REPEATS + 1):
                        cell_number += 1
                        if (pattern, mode, flows, repeat) in done:
                            continue
                        record = run_cell(intent, pattern, flows, pair_bytes_for(intent, pattern), None, cell_number)
                        record.update({"routing": mode, "repeat": repeat})
                        results["cells"].append(record)
                        RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
                        print(json.dumps({
                            "pattern": pattern, "routing": mode, "flows": flows, "repeat": repeat,
                            "job": round(record["job_time_seconds"], 3),
                            "rx_job": round(record["receiver_job_time_seconds"] or -1, 3),
                            "max_link_bound": round(record["max_link_bound_seconds"], 3),
                            "imbalance": round(record["worst_leaf_imbalance"], 3),
                            "skew": round(record["start_skew_seconds"], 4),
                            "drops": record["qdisc_drops_total"],
                        }))
    finally:
        set_routing(intent, "L3", "ring")
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["baseline", "run"])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    baseline() if args.command == "baseline" else run(args.resume)
