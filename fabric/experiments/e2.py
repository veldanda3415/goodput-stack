from __future__ import annotations

import json
import re
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fabric.experiments.e1 import link_tx_bytes, wait_for_gateway_probes
from fabric.intent.schema.validate import load_intent
from fabric.tests.lab import node_json, node_result


ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e2-results.json"
PING_INTERVAL_SECONDS = 0.01
PING_DURATION_SECONDS = 15
REPEATS = 3
POLL_INTERVAL_SECONDS = 5
ADJACENCY_TIMEOUT_SECONDS = 150
TRACKED_PEERS = (
    ("leaf1", "eth1"),
    ("leaf1", "eth2"),
    ("spine1", "eth1"),
    ("spine2", "eth1"),
)
BFD_PEERS = {
    "leaf1": {"eth1", "eth2"},
    "spine1": {"eth1"},
    "spine2": {"eth1"},
}


def command_args(intent: dict[str, Any], node: str, command: str) -> list[str]:
    return [
        "containerlab", "exec", "--runtime", "podman",
        "--name", intent["name"],
        "--label", f"clab-node-name={node}",
        "--format", "json", "--log-level", "error",
        "--cmd", command,
    ]


def start_ping(
    intent: dict[str, Any],
    host: str,
    source_ip: str,
    target_ip: str,
    duration_seconds: int = PING_DURATION_SECONDS,
) -> subprocess.Popen[str]:
    command = (
        f"ping -D -n -i {PING_INTERVAL_SECONDS} -w {duration_seconds} "
        f"-I {source_ip} {target_ip}"
    )
    return subprocess.Popen(
        command_args(intent, host, command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def finish_ping(
    intent: dict[str, Any],
    host: str,
    process: subprocess.Popen[str],
    duration_seconds: int = PING_DURATION_SECONDS,
) -> dict[str, Any]:
    stdout, stderr = process.communicate(timeout=duration_seconds + 15)
    if process.returncode != 0:
        raise RuntimeError(
            f"containerlab exec failed for ping on {host}: "
            f"exit={process.returncode}; stdout={stdout!r}; stderr={stderr!r}"
        )
    container = f"clab-{intent['name']}-{host}"
    result = json.loads(stdout)[container][0]
    if result["return-code"] not in (0, 1):
        raise RuntimeError(
            f"ping command failed on {host}: exit={result['return-code']}; "
            f"stdout={result['stdout']!r}; stderr={result['stderr']!r}"
        )
    if not isinstance(result["stdout"], str):
        raise RuntimeError(f"ping output from {host} was not text: {result['stdout']!r}")
    return result


def find_host(intent: dict[str, Any], leaf: str, rail: str) -> tuple[str, dict[str, Any]]:
    matches = [
        (host["name"], nic)
        for host in intent["hosts"]
        for nic in host["nics"]
        if nic["leaf"] == leaf and nic["rail"] == rail
    ]
    if not matches:
        raise RuntimeError(f"no {rail} host attachment on {leaf}")
    return sorted(matches, key=lambda item: item[0])[0]


def measure_ping_path(
    intent: dict[str, Any],
    host: str,
    source_ip: str,
    target_ip: str,
    uplinks: list[str],
) -> tuple[str, dict[str, Any]]:
    probe_wait = wait_for_gateway_probes()
    before = {interface: link_tx_bytes("leaf1", interface) for interface in uplinks}
    process = start_ping(intent, host, source_ip, target_ip, duration_seconds=2)
    result = finish_ping(intent, host, process, duration_seconds=2)
    after = {interface: link_tx_bytes("leaf1", interface) for interface in uplinks}
    deltas = {
        interface: after[interface] - before[interface]
        for interface in uplinks
    }
    summary = re.search(
        r"(?P<sent>\d+) packets transmitted,\s*(?P<received>\d+) received,\s*"
        r"(?P<loss>[\d.]+)% packet loss",
        result["stdout"],
    )
    if summary is None or int(summary["received"]) == 0:
        raise RuntimeError(f"ping path probe got no replies: {result['stdout'][-1000:]!r}")
    if not deltas or max(deltas.values()) <= 0:
        raise RuntimeError(f"could not identify the ping's leaf1 uplink: {deltas!r}")
    selected = max(deltas, key=deltas.get)
    return selected, {
        "command": (
            f"ping -D -n -i {PING_INTERVAL_SECONDS} -w 2 "
            f"-I {source_ip} {target_ip}"
        ),
        "gateway_probe_wait_seconds": probe_wait,
        "transmitted": int(summary["sent"]),
        "received": int(summary["received"]),
        "packet_loss_percent": float(summary["loss"]),
        "counter_before_tx_bytes": before,
        "counter_after_tx_bytes": after,
        "counter_delta_tx_bytes": deltas,
        "selected_leaf_interface": selected,
    }


def find_fault_link(
    intent: dict[str, Any],
    leaf_interface: str,
) -> tuple[str, str, str, str]:
    links = [
        link
        for link in intent["links"]
        if link["kind"] == "fabric"
        and any(
            endpoint["node"] == "leaf1" and endpoint["interface"] == leaf_interface
            for endpoint in (link["a"], link["b"])
        )
    ]
    if len(links) != 1:
        raise RuntimeError(f"expected one fabric link for leaf1:{leaf_interface}, got {links!r}")
    link = links[0]
    leaf = next(endpoint for endpoint in (link["a"], link["b"]) if endpoint["node"] == "leaf1")
    spine = next(endpoint for endpoint in (link["a"], link["b"]) if endpoint["node"] != "leaf1")
    return link["name"], leaf["interface"], spine["node"], spine["interface"]


def set_bfd(enabled: bool) -> None:
    peer_groups = (
        ("leaf1", 65101, "FABRIC"),
        ("spine1", 65000, "PEER_LEAF1"),
        ("spine2", 65000, "PEER_LEAF1"),
    )
    for node, asn, peer_group in peer_groups:
        bfd_command = (
            f"neighbor {peer_group} bfd profile FABRIC"
            if enabled
            else f"no neighbor {peer_group} bfd"
        )
        command = (
            f"vtysh -c 'configure terminal' -c 'router bgp {asn}' "
            f"-c '{bfd_command}' -c 'end'"
        )
        node_result(node, command)


def peer_state(node: str, interface: str) -> str | None:
    peers = node_json(node, 'vtysh -c "show bgp summary json"')["ipv4Unicast"]["peers"]
    peer = peers.get(interface)
    return peer["state"] if peer else None


def bfd_states(node: str) -> dict[str, str]:
    peers = node_json(node, 'vtysh -c "show bfd peers brief json"')
    return {peer["interface"]: peer["status"] for peer in peers}


def link_state(node: str, interface: str) -> dict[str, Any]:
    links = node_json(node, f"ip -j link show dev {interface}")
    if len(links) != 1:
        raise RuntimeError(f"expected one link for {node}:{interface}, got {links!r}")
    return {"operstate": links[0]["operstate"], "flags": links[0]["flags"]}


def adjacency_snapshot(
    leaf_interface: str,
    spine_node: str,
    spine_interface: str,
) -> dict[str, Any]:
    return {
        "bgp": {
            f"{node}:{interface}": peer_state(node, interface)
            for node, interface in TRACKED_PEERS
        },
        "bfd": {
            node: bfd_states(node)
            for node in BFD_PEERS
        },
        "link": {
            "leaf1": link_state("leaf1", leaf_interface),
            spine_node: link_state(spine_node, spine_interface),
        },
    }


def adjacency_ready(
    bfd_enabled: bool,
    leaf_interface: str,
    spine_node: str,
    spine_interface: str,
) -> tuple[bool, dict[str, Any]]:
    snapshot = adjacency_snapshot(leaf_interface, spine_node, spine_interface)
    bgp_ready = all(state == "Established" for state in snapshot["bgp"].values())
    if bfd_enabled:
        bfd_ready = all(
            snapshot["bfd"][node].get(interface) == "up"
            for node, interfaces in BFD_PEERS.items()
            for interface in interfaces
        )
    else:
        bfd_ready = all(
            interface not in snapshot["bfd"][node]
            for node, interfaces in BFD_PEERS.items()
            for interface in interfaces
        )
    return bgp_ready and bfd_ready, snapshot


def wait_for_adjacencies(
    bfd_enabled: bool,
    leaf_interface: str,
    spine_node: str,
    spine_interface: str,
) -> float:
    started = time.monotonic()
    deadline = started + ADJACENCY_TIMEOUT_SECONDS
    while True:
        ready, snapshot = adjacency_ready(
            bfd_enabled,
            leaf_interface,
            spine_node,
            spine_interface,
        )
        if ready:
            return round(time.monotonic() - started, 2)
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"timed out waiting for BGP/BFD recovery with BFD "
                f"{'on' if bfd_enabled else 'off'}: {snapshot!r}"
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def apply_fault(
    kind: str,
    spine_node: str,
    leaf_interface: str,
    spine_interface: str,
) -> None:
    if kind == "carrier-down":
        node_result(spine_node, f"ip link set dev {spine_interface} down")
        return
    if kind == "silent-loss":
        for node, interface in (("leaf1", leaf_interface), (spine_node, spine_interface)):
            qdisc = node_result(node, f"tc qdisc show dev {interface}")["stdout"]
            if "noqueue" not in qdisc:
                raise RuntimeError(
                    f"refusing to replace pre-existing qdisc on {node}:{interface}: {qdisc!r}"
                )
        node_result(
            "leaf1",
            f"tc qdisc replace dev {leaf_interface} root netem loss 100%",
        )
        node_result(
            spine_node,
            f"tc qdisc replace dev {spine_interface} root netem loss 100%",
        )
        for node, interface in (("leaf1", leaf_interface), (spine_node, spine_interface)):
            state = link_state(node, interface)
            if state["operstate"] != "UP" or "LOWER_UP" not in state["flags"]:
                raise RuntimeError(f"silent-loss fault changed carrier on {node}:{interface}: {state}")
        return
    raise ValueError(f"unknown fault kind {kind!r}")


def restore_fault(
    kind: str,
    spine_node: str,
    leaf_interface: str,
    spine_interface: str,
) -> None:
    if kind == "carrier-down":
        node_result(spine_node, f"ip link set dev {spine_interface} up")
    elif kind == "silent-loss":
        for node, interface in (("leaf1", leaf_interface), (spine_node, spine_interface)):
            qdisc = node_result(node, f"tc qdisc show dev {interface}")["stdout"]
            if "netem" in qdisc:
                node_result(node, f"tc qdisc del dev {interface} root")
            elif "noqueue" not in qdisc:
                raise RuntimeError(
                    f"unexpected qdisc while restoring {node}:{interface}: {qdisc!r}"
                )
    else:
        raise ValueError(f"unknown fault kind {kind!r}")


def ping_measurements(output: str, fault_epoch: float) -> dict[str, Any]:
    summary = re.search(
        r"(?P<sent>\d+) packets transmitted,\s*(?P<received>\d+) received,\s*"
        r"(?P<loss>[\d.]+)% packet loss",
        output,
    )
    if summary is None:
        raise RuntimeError(f"could not parse ping summary: {output[-1000:]!r}")
    replies = [
        (float(match.group("epoch")), int(match.group("sequence")))
        for match in re.finditer(
            r"^\[(?P<epoch>\d+(?:\.\d+)?)\].*icmp_seq=(?P<sequence>\d+)",
            output,
            flags=re.MULTILINE,
        )
    ]
    before = [reply for reply in replies if reply[0] < fault_epoch]
    after = [reply for reply in replies if reply[0] >= fault_epoch]
    last_before = before[-1] if before else None
    first_after = after[0] if after else None
    baseline_gaps = [
        current[0] - previous[0]
        for previous, current in zip(before, before[1:])
    ]
    baseline_reply_interval_ms = (
        round(statistics.median(baseline_gaps) * 1000, 2)
        if baseline_gaps
        else None
    )
    if last_before and first_after:
        reply_gap_ms = round((first_after[0] - last_before[0]) * 1000, 2)
    else:
        reply_gap_ms = None
    fault_pairs = [
        (previous, current)
        for previous, current in zip(replies, replies[1:])
        if current[0] >= fault_epoch
    ]
    if fault_pairs:
        gap_before, gap_after = max(
            fault_pairs,
            key=lambda pair: (
                max(0, pair[1][1] - pair[0][1] - 1),
                pair[1][0] - pair[0][0],
            ),
        )
        max_reply_gap_ms = round((gap_after[0] - gap_before[0]) * 1000, 2)
        lost_probes = max(0, gap_after[1] - gap_before[1] - 1)
        lost_probes_during_fault = sum(
            max(0, current[1] - previous[1] - 1)
            for previous, current in fault_pairs
        )
        if lost_probes == 0:
            estimated_loss_window_ms = 0.0
        elif baseline_reply_interval_ms is not None:
            estimated_loss_window_ms = round(
                max(0, max_reply_gap_ms - baseline_reply_interval_ms),
                2,
            )
        else:
            estimated_loss_window_ms = None
        loss_pairs = [
            (previous, current)
            for previous, current in fault_pairs
            if current[1] - previous[1] > 1
        ]
        fault_to_recovery_ms = (
            round((loss_pairs[0][1][0] - fault_epoch) * 1000, 2)
            if loss_pairs
            else 0.0
        )
    else:
        max_reply_gap_ms = None
        estimated_loss_window_ms = None
        fault_to_recovery_ms = None
        lost_probes = None
        lost_probes_during_fault = None
    return {
        "transmitted": int(summary["sent"]),
        "received": int(summary["received"]),
        "packet_loss_percent": float(summary["loss"]),
        "successful_replies": len(replies),
        "last_reply_before_fault": last_before,
        "first_reply_after_fault": first_after,
        "reply_gap_ms": reply_gap_ms,
        "baseline_reply_interval_ms": baseline_reply_interval_ms,
        "max_reply_gap_ms_during_fault": max_reply_gap_ms,
        "estimated_loss_window_ms": estimated_loss_window_ms,
        "fault_to_recovery_ms": fault_to_recovery_ms,
        "lost_probe_count_between_replies": lost_probes,
        "lost_probe_count_during_fault": lost_probes_during_fault,
    }


def run_trial(
    intent: dict[str, Any],
    source_host: str,
    source_ip: str,
    target_ip: str,
    fault_kind: str,
    bfd_enabled: bool,
    repeat: int,
    fault_link: str,
    spine_node: str,
    leaf_interface: str,
    spine_interface: str,
) -> dict[str, Any]:
    probe_wait = wait_for_gateway_probes()
    pre_wait = wait_for_adjacencies(
        bfd_enabled,
        leaf_interface,
        spine_node,
        spine_interface,
    )
    ping_command = (
        f"ping -D -n -i {PING_INTERVAL_SECONDS} -w {PING_DURATION_SECONDS} "
        f"-I {source_ip} {target_ip}"
    )
    ping_process = start_ping(intent, source_host, source_ip, target_ip)
    time.sleep(1)
    if ping_process.poll() is not None:
        finish_ping(intent, source_host, ping_process)
        raise RuntimeError(f"ping exited before fault injection: {ping_command}")

    fault_applied = False
    fault_epoch = 0.0
    try:
        fault_applied = True
        fault_epoch = time.time()
        apply_fault(fault_kind, spine_node, leaf_interface, spine_interface)
        ping_result = finish_ping(intent, source_host, ping_process)
        failure_snapshot = adjacency_snapshot(
            leaf_interface,
            spine_node,
            spine_interface,
        )
        link_during_fault = failure_snapshot["link"]
    finally:
        if fault_applied:
            restore_fault(fault_kind, spine_node, leaf_interface, spine_interface)
    restored_epoch = time.time()

    measurements = ping_measurements(ping_result["stdout"], fault_epoch)
    record = {
        "bfd_enabled": bfd_enabled,
        "fault": fault_kind,
        "fault_link": fault_link,
        "fault_spine": spine_node,
        "repeat": repeat,
        "gateway_probe_wait_seconds": probe_wait,
        "wait_before_trial_seconds": pre_wait,
        "ping_command": ping_command,
        "fault_epoch": round(fault_epoch, 6),
        "fault_restored_epoch": round(restored_epoch, 6),
        "fault_active_seconds": round(restored_epoch - fault_epoch, 3),
        "ping_return_code": ping_result["return-code"],
        "link_during_fault": link_during_fault,
        "adjacency_during_fault": failure_snapshot,
        **measurements,
    }
    return record


def write_results(results: dict[str, Any]) -> None:
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def run() -> None:
    intent = load_intent()
    source_host, source_nic = find_host(intent, "leaf1", "A")
    target_host, target_nic = find_host(intent, "leaf2", "A")
    source_ip = source_nic["address"].split("/")[0]
    target_ip = target_nic["address"].split("/")[0]
    for leaf in ("leaf1", "leaf2"):
        node_result(leaf, "sysctl -w net.ipv4.fib_multipath_hash_policy=0")
        observed = node_result(
            leaf, "sysctl -n net.ipv4.fib_multipath_hash_policy"
        )["stdout"]
        if str(observed).strip() != "0":
            raise RuntimeError(f"{leaf}: expected L3 hash policy 0, got {observed!r}")
    uplinks = sorted(
        endpoint["interface"]
        for link in intent["links"]
        if link["kind"] == "fabric"
        for endpoint in (link["a"], link["b"])
        if endpoint["node"] == "leaf1"
    )
    leaf_interface, path_probe = measure_ping_path(
        intent,
        source_host,
        source_ip,
        target_ip,
        uplinks,
    )
    fault_link, leaf_interface, spine_node, spine_interface = find_fault_link(
        intent,
        leaf_interface,
    )

    results: dict[str, Any] = {
        "started_at": datetime.now().astimezone().isoformat(),
        "label": "EMULATED",
        "measurement": "high-rate ICMP ping; no iperf3 used",
        "runtime": "containerlab with Podman",
        "images": intent["images"],
        "kernel_release": node_result("leaf1", "uname -r")["stdout"].strip(),
        "frr_timers": {
            "bgp_hold_seconds": intent["bgp"]["hold_seconds"],
            "bgp_keepalive_seconds": intent["bgp"]["keepalive_seconds"],
            "bfd_transmit_ms": intent["bfd"]["transmit_ms"],
            "bfd_receive_ms": intent["bfd"]["receive_ms"],
            "bfd_detect_multiplier": intent["bfd"]["detect_multiplier"],
        },
        "ping_duration_seconds": PING_DURATION_SECONDS,
        "ping_interval_seconds": PING_INTERVAL_SECONDS,
        "repeats_per_case": REPEATS,
        "source": {"host": source_host, "ip": source_ip, "rail": "A"},
        "target": {"host": target_host, "ip": target_ip, "rail": "A"},
        "path_probe": {
            **path_probe,
            "selected_spine": spine_node,
            "selected_spine_interface": spine_interface,
        },
        "fault_link": {
            "name": fault_link,
            "leaf1_interface": leaf_interface,
            "spine_node": spine_node,
            "spine_interface": spine_interface,
        },
        "bfd_off_scope": [
            "leaf1 peer-group FABRIC",
            "spine1 peer-group PEER_LEAF1",
            "spine2 peer-group PEER_LEAF1",
        ],
        "runs": [],
    }
    write_results(results)

    try:
        for fault_kind in ("carrier-down", "silent-loss"):
            for repeat in range(1, REPEATS + 1):
                record = run_trial(
                    intent,
                    source_host,
                    source_ip,
                    target_ip,
                    fault_kind,
                    True,
                    repeat,
                    fault_link,
                    spine_node,
                    leaf_interface,
                    spine_interface,
                )
                results["runs"].append(record)
                write_results(results)
                print(json.dumps(record, sort_keys=True))

        wait_for_adjacencies(
            True,
            leaf_interface,
            spine_node,
            spine_interface,
        )
        set_bfd(False)
        wait_for_adjacencies(
            False,
            leaf_interface,
            spine_node,
            spine_interface,
        )
        for fault_kind in ("carrier-down", "silent-loss"):
            for repeat in range(1, REPEATS + 1):
                record = run_trial(
                    intent,
                    source_host,
                    source_ip,
                    target_ip,
                    fault_kind,
                    False,
                    repeat,
                    fault_link,
                    spine_node,
                    leaf_interface,
                    spine_interface,
                )
                results["runs"].append(record)
                write_results(results)
                print(json.dumps(record, sort_keys=True))
        wait_for_adjacencies(
            False,
            leaf_interface,
            spine_node,
            spine_interface,
        )
    finally:
        set_bfd(True)
        results["bfd_restore_command_applied"] = True
        write_results(results)
        results["final_recovery_wait_seconds"] = wait_for_adjacencies(
            True,
            leaf_interface,
            spine_node,
            spine_interface,
        )
        results["bfd_restored"] = True

    results["completed_at"] = datetime.now().astimezone().isoformat()
    write_results(results)
    print(f"Wrote {len(results['runs'])} runs to {RESULT_PATH}")


if __name__ == "__main__":
    run()
