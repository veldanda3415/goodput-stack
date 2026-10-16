"""Run collective-shaped TCP and SOFT-ROCE traffic on the EMULATED fabric."""
from __future__ import annotations

import base64
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.experiments.e1 import active_gateway_probes
from fabric.experiments.e3.bth_decode import decode, pcap_records
from fabric.experiments.e3.run import (
    background,
    endpoints as rdma_endpoints,
    finish,
    finish_capture,
    parse_perftest,
    roce_v2_gid,
    text,
)
from fabric.intent.schema.validate import load_intent
from fabric.tests.lab import node_json, node_result

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e5-results.json"
CAPTURE_DIR = ROOT / "fabric" / "experiments" / "e5"
POLICIES = (0, 1)
FLOW_COUNTS = (1, 4, 16)
PATTERNS = ("ring", "all-to-all")
REPEATS = 3
BYTES_PER_FLOW = 256 * 1024
TCP_DURATION_SECONDS = 5
TCP_PORT_BASE = 5400
TCP_SERVER_TIMEOUT = 25
TCP_CLIENT_TIMEOUT = 20
RDMA_SIZE_BYTES = 65536
RDMA_ITERATIONS = 256
RDMA_PORT_BASE = 18600
RDMA_CAPTURE_PACKETS = 128
RDMA_CAPTURE_TIMEOUT = 4
UPLINK_COUNTER_COMMAND = "ip -j -s link show"


def rail_a_hosts(intent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    hosts: dict[str, dict[str, Any]] = {}
    for host in intent["hosts"]:
        for nic in host["nics"]:
            if nic["rail"] == "A":
                hosts[host["name"]] = {
                    "name": host["name"],
                    "ip": nic["address"].split("/")[0],
                    "leaf": nic["leaf"],
                    "interface": nic["interface"],
                }
    if len(hosts) != 4 or {host["leaf"] for host in hosts.values()} != {"leaf1", "leaf2"}:
        raise RuntimeError(f"E5 needs four rail-A hosts on leaf1/leaf2; found {hosts!r}")
    return hosts


def collective_pairs(
    hosts: dict[str, dict[str, Any]], pattern: str
) -> list[tuple[str, str]]:
    names = sorted(hosts)
    if len(names) != 4:
        raise ValueError(f"collective patterns require four hosts, got {len(names)}")
    if pattern == "ring":
        ordered = (names[0], names[2], names[1], names[3])
        return [
            (ordered[index], ordered[(index + 1) % len(ordered)])
            for index in range(len(ordered))
        ]
    if pattern == "all-to-all":
        return [(source, dest) for source in names for dest in names if source != dest]
    raise ValueError(f"unsupported collective pattern: {pattern}")


def leaf_uplinks(intent: dict[str, Any]) -> dict[str, list[str]]:
    leaves = [
        node["name"] for node in intent["nodes"] if node["role"] == "leaf"
    ]
    uplinks = {leaf: [] for leaf in leaves}
    for link in intent["links"]:
        if link["kind"] != "fabric":
            continue
        for endpoint in (link["a"], link["b"]):
            if endpoint["node"] in uplinks:
                uplinks[endpoint["node"]].append(endpoint["interface"])
    for leaf, interfaces in uplinks.items():
        uplinks[leaf] = sorted(interfaces)
        if len(interfaces) != intent["ecmp_width"]:
            raise RuntimeError(
                f"{leaf} has {len(interfaces)} fabric uplinks; expected {intent['ecmp_width']}"
            )
    return uplinks


def uplink_snapshot(
    uplinks: dict[str, list[str]],
) -> dict[str, dict[str, int]]:
    snapshot: dict[str, dict[str, int]] = {}
    for leaf, interfaces in uplinks.items():
        links = node_json(leaf, UPLINK_COUNTER_COMMAND)
        by_name = {link.get("ifname"): link for link in links}
        snapshot[leaf] = {}
        for interface in interfaces:
            link = by_name.get(interface)
            if not link or "stats64" not in link:
                raise RuntimeError(f"missing TX counters for {leaf}:{interface}: {link!r}")
            snapshot[leaf][interface] = int(link["stats64"]["tx"]["bytes"])
    return snapshot


def counter_deltas(
    before: dict[str, dict[str, int]],
    after: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    deltas = {
        leaf: {
            interface: after[leaf][interface] - value
            for interface, value in interfaces.items()
        }
        for leaf, interfaces in before.items()
    }
    if any(delta < 0 for links in deltas.values() for delta in links.values()):
        raise RuntimeError(f"uplink TX counter moved backwards: {deltas!r}")
    return deltas


def summarize_uplinks(
    deltas: dict[str, dict[str, int]],
) -> dict[str, Any]:
    per_leaf: dict[str, Any] = {}
    active_ratios: list[float] = []
    for leaf, interfaces in deltas.items():
        values = list(interfaces.values())
        total = sum(values)
        if total == 0:
            per_leaf[leaf] = {
                "tx_bytes": interfaces,
                "total_tx_bytes": 0,
                "max_mean_imbalance": None,
                "percent": {name: 0.0 for name in interfaces},
            }
            continue
        mean = total / len(values)
        ratio = max(values) / mean
        active_ratios.append(ratio)
        per_leaf[leaf] = {
            "tx_bytes": interfaces,
            "total_tx_bytes": total,
            "max_mean_imbalance": ratio,
            "percent": {
                name: round(100 * value / total, 2)
                for name, value in interfaces.items()
            },
        }
    return {
        "per_leaf": per_leaf,
        "worst_active_leaf_imbalance": max(active_ratios) if active_ratios else None,
        "total_uplink_tx_bytes": sum(
            sum(interfaces.values()) for interfaces in deltas.values()
        ),
    }


def parse_iperf_streams(
    document: dict[str, Any], expected_bytes_per_flow: int
) -> list[dict[str, Any]]:
    try:
        streams = document["end"]["streams"]
    except (KeyError, TypeError) as error:
        raise RuntimeError(f"iperf3 JSON has no end.streams: {document!r}") from error
    if not streams:
        raise RuntimeError(f"iperf3 JSON contains no streams: {document!r}")
    stream_intervals: dict[int, list[dict[str, Any]]] = {}
    for interval in document.get("intervals", []):
        for sample in interval.get("streams", []):
            socket = int(sample["socket"])
            stream_intervals.setdefault(socket, []).append(sample)
    records = []
    for index, stream in enumerate(streams, start=1):
        receiver = stream.get("receiver")
        sender = stream.get("sender")
        if not isinstance(receiver, dict) or not isinstance(sender, dict):
            raise RuntimeError(f"iperf3 stream lacks sender/receiver data: {stream!r}")
        received = int(receiver["bytes"])
        if received < expected_bytes_per_flow:
            raise RuntimeError(
                f"iperf3 stream {index} received {received} B; "
                f"expected at least {expected_bytes_per_flow} B; "
                f"sender={sender!r}; receiver={receiver!r}; "
                f"sum_received={document['end'].get('sum_received')!r}"
            )
        socket = int(receiver["socket"])
        cumulative = 0
        time_to_target = None
        for sample in stream_intervals.get(socket, []):
            interval_bytes = int(sample["bytes"])
            if cumulative + interval_bytes >= expected_bytes_per_flow:
                duration = float(sample["end"]) - float(sample["start"])
                if duration <= 0 or interval_bytes <= 0:
                    raise RuntimeError(
                        f"invalid iperf3 interval for stream socket {socket}: {sample!r}"
                    )
                remaining = expected_bytes_per_flow - cumulative
                time_to_target = (
                    float(sample["start"])
                    + duration * remaining / interval_bytes
                )
                break
            cumulative += interval_bytes
        if time_to_target is None:
            raise RuntimeError(
                f"iperf3 intervals do not show stream socket {socket} reaching "
                f"{expected_bytes_per_flow} B; intervals={stream_intervals.get(socket)!r}"
            )
        records.append({
            "stream_index": index,
            "sender_socket": sender.get("socket"),
            "sent_bytes": int(sender["bytes"]),
            "received_bytes": received,
            "throughput_gbps": float(receiver["bits_per_second"]) / 1e9,
            "elapsed_seconds": float(receiver["seconds"]),
            "time_to_target_bytes_seconds": time_to_target,
        })
    return records


def start_iperf_server(host: str, port: int) -> subprocess.Popen[str]:
    return background(
        host,
        f"timeout {TCP_SERVER_TIMEOUT} iperf3 -s -1 -p {port}",
    )


def run_tcp_cell(
    hosts: dict[str, dict[str, Any]],
    uplinks: dict[str, list[str]],
    pattern: str,
    flows_per_pair: int,
    repeat: int,
    cell_number: int,
    duration_seconds: int = TCP_DURATION_SECONDS,
) -> dict[str, Any]:
    pairs = collective_pairs(hosts, pattern)
    before = uplink_snapshot(uplinks)
    cell_started = time.monotonic()
    servers: list[tuple[str, subprocess.Popen[str]]] = []
    for pair_index, (_, destination) in enumerate(pairs):
        port = TCP_PORT_BASE + cell_number * 20 + pair_index
        servers.append((destination, start_iperf_server(destination, port)))
    time.sleep(0.6)

    clients: list[dict[str, Any]] = []
    for pair_index, (source, destination) in enumerate(pairs):
        port = TCP_PORT_BASE + cell_number * 20 + pair_index
        source_host = hosts[source]
        destination_host = hosts[destination]
        command = (
            f"timeout {TCP_CLIENT_TIMEOUT} iperf3 -c {destination_host['ip']} "
            f"-B {source_host['ip']} -p {port} -P {flows_per_pair} "
            f"-t {duration_seconds} --json"
        )
        launched = time.monotonic()
        process = background(source, command)
        clients.append({
            "source": source,
            "destination": destination,
            "command": command,
            "launch_offset_seconds": launched - cell_started,
            "process": process,
        })

    pair_results = []
    flow_results = []
    cell_errors: list[str] = []
    for client in clients:
        try:
            output = finish(
                client["source"], client["process"], timeout=TCP_CLIENT_TIMEOUT + 20
            )
            document = json.loads(output)
            flows = parse_iperf_streams(document, BYTES_PER_FLOW)
        except (AssertionError, RuntimeError, json.JSONDecodeError) as error:
            message = (
                f"{client['source']}->{client['destination']} failed: "
                f"{client['command']}; {error}"
            )
            cell_errors.append(message)
            continue
        for flow in flows:
            flow["source"] = client["source"]
            flow["destination"] = client["destination"]
            flow["finish_offset_seconds"] = (
                client["launch_offset_seconds"]
                + flow["time_to_target_bytes_seconds"]
            )
            flow_results.append(flow)
        pair_results.append({
            "source": client["source"],
            "destination": client["destination"],
            "command": client["command"],
            "iperf3_version": document["start"].get("version"),
            "received_bytes": document["end"]["sum_received"]["bytes"],
            "received_gbps": (
                document["end"]["sum_received"]["bits_per_second"] / 1e9
            ),
            "flows": flows,
            "iperf3_json": document,
        })
    for host, server in servers:
        try:
            finish(host, server, timeout=TCP_SERVER_TIMEOUT + 20)
        except (AssertionError, RuntimeError) as error:
            cell_errors.append(f"iperf3 server failed on {host}: {error}")
    after = uplink_snapshot(uplinks)
    deltas = counter_deltas(before, after)
    uplink_summary = summarize_uplinks(deltas)
    if cell_errors:
        raise RuntimeError(
            "; ".join(cell_errors)
            + f"; partial uplink tx deltas={deltas!r}"
        )
    job_time = max(flow["finish_offset_seconds"] for flow in flow_results)
    imbalance = uplink_summary["worst_active_leaf_imbalance"]
    # MODEL, not evidence: job_time / imbalance restates the imbalance. It
    # only bounds job time if uplinks are the bottleneck, which unshaped E5
    # disproved (job time is dominated by serial client launch offsets).
    model_bound = job_time / imbalance if imbalance else None
    return {
        "transport": "TCP",
        "pattern": pattern,
        "flows_per_pair": flows_per_pair,
        "repeat": repeat,
        "duration_seconds": duration_seconds,
        "bytes_per_flow_target": BYTES_PER_FLOW,
        "pairs": [[source, destination] for source, destination in pairs],
        "pair_results": pair_results,
        "flows": flow_results,
        "job_time_seconds": job_time,
        "job_time_slowest_flow": max(
            flow_results,
            key=lambda flow: flow["finish_offset_seconds"],
        ),
        "uplink_delta_tx_bytes": deltas,
        "uplink_summary": uplink_summary,
        "imbalance_implied_bound_model": {
            "label": "MODEL (imbalance-implied bound), not a measurement",
            "method": (
                "job time divided by worst active-leaf max/mean uplink bytes; "
                "valid only if job time scales with max uplink load, i.e. the "
                "uplinks are the bottleneck"
            ),
            "model_job_time_seconds": model_bound,
            "imbalance_minus_one_percent": (
                100 * (imbalance - 1) if imbalance is not None else None
            ),
        },
        "last_client_launch_offset_seconds": max(
            client["launch_offset_seconds"] for client in clients
        ),
        "slowest_flow_time_to_target_seconds": max(
            flow["time_to_target_bytes_seconds"] for flow in flow_results
        ),
        "counter_before_tx_bytes": before,
        "counter_after_tx_bytes": after,
        "wall_seconds": time.monotonic() - cell_started,
    }


def capture_roce(spine: str, tag: str) -> dict[str, Any]:
    tap = f"{spine}-tap"
    remote_path = f"/tmp/{tag}-{spine}-{time.time_ns()}.pcap"
    interface = "eth1"
    command = (
        f"timeout {RDMA_CAPTURE_TIMEOUT} tcpdump -n -i {interface} -s 128 "
        f"-c {RDMA_CAPTURE_PACKETS} -w {remote_path} 'udp port 4791'"
    )
    process = background(tap, command)
    return {"tap": tap, "remote_path": remote_path, "process": process}


def finish_roce_capture(tap_info: dict[str, Any], tag: str) -> dict[str, Any]:
    tap = tap_info["tap"]
    remote_path = tap_info["remote_path"]
    result = finish_capture(tap, tap_info["process"])
    raw = base64.b64decode(
        text(tap, f"base64 -w0 {remote_path}").strip(),
        validate=True,
    )
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = CAPTURE_DIR / f"{tag}-{tap}.pcap"
    local_path.write_bytes(raw)
    text(tap, f"rm -f -- {remote_path}")
    packets = [
        packet
        for linktype, frame in pcap_records(raw)
        if (packet := decode(frame, linktype)) is not None
    ]
    return {
        "file": str(local_path.relative_to(ROOT)),
        "bytes": len(raw),
        "tcpdump_return_code": result["return-code"],
        "packets": len(packets),
        "udp_source_ports": sorted({packet["udp_src_port"] for packet in packets}),
        "ecn_bits": {
            str(value): sum(packet["ecn"] == value for packet in packets)
            for value in range(4)
        },
    }


def run_roce_cell(
    uplinks: dict[str, list[str]],
    hash_policy: int,
    qps: int,
    repeat: int,
) -> dict[str, Any]:
    source, destination = rdma_endpoints()["vmhost1:A"], rdma_endpoints()["vmhost2:A"]
    source_gid = roce_v2_gid(source)["roce_v2_index"]
    destination_gid = roce_v2_gid(destination)["roce_v2_index"]
    port = RDMA_PORT_BASE + hash_policy * 1000 + qps * 10 + repeat
    common = (
        f"-s {RDMA_SIZE_BYTES} -n {RDMA_ITERATIONS} --report_gbits -F "
        f"--tclass 104 -q {qps} -p {port}"
    )
    server_command = (
        f"timeout 25 ib_write_bw -d {destination['device']} -x {destination_gid} "
        f"{common}"
    )
    client_command = (
        f"ib_write_bw -d {source['device']} -x {source_gid} {common} "
        f"--bind_source_ip {source['ip']} {destination['ip']}"
    )
    tag = f"l{hash_policy}-q{qps}-r{repeat}"
    before = uplink_snapshot(uplinks)
    captures = [capture_roce(spine, tag) for spine in ("spine1", "spine2")]
    server = background(destination["host"], server_command)
    time.sleep(0.7)
    started = time.monotonic()
    client = background(source["host"], client_command)
    client_output = finish(source["host"], client, timeout=25)
    elapsed = time.monotonic() - started
    server_output = finish(destination["host"], server, timeout=30)
    capture_results = {
        item["tap"]: finish_roce_capture(item, tag) for item in captures
    }
    after = uplink_snapshot(uplinks)
    deltas = counter_deltas(before, after)
    uplink_summary = summarize_uplinks(deltas)
    parsed = parse_perftest("ib_write_bw", client_output, RDMA_SIZE_BYTES)
    aggregate_gbps = parsed["bw_avg_gbps"]
    return {
        "transport": "SOFT-ROCE",
        "pattern": "two-VM parallel QPs (supplemental; two VMs cannot realize the four-host collective)",
        "hash_policy": hash_policy,
        "qps": qps,
        "repeat": repeat,
        "bytes_per_qp_target": RDMA_SIZE_BYTES * RDMA_ITERATIONS,
        "aggregate_gbps": aggregate_gbps,
        "derived_mean_gbps_per_qp": aggregate_gbps / qps,
        "per_qp_rate_note": (
            "derived equal-share mean; perftest reports aggregate bandwidth, "
            "not individual QP rates"
        ),
        "job_time_seconds": elapsed,
        "server_command": server_command,
        "client_command": client_command,
        "client_output": client_output,
        "server_output_tail": "\n".join(server_output.splitlines()[-5:]),
        "perftest_parsed": parsed,
        "capture_by_tap": capture_results,
        "distinct_udp_source_ports": sorted({
            port
            for capture in capture_results.values()
            for port in capture["udp_source_ports"]
        }),
        "uplink_delta_tx_bytes": deltas,
        "uplink_summary": uplink_summary,
        "counter_before_tx_bytes": before,
        "counter_after_tx_bytes": after,
    }


def set_hash_policy(leaves: list[str], policy: int) -> None:
    for leaf in leaves:
        node_result(leaf, f"sysctl -w net.ipv4.fib_multipath_hash_policy={policy}")
        observed = node_result(
            leaf, "sysctl -n net.ipv4.fib_multipath_hash_policy"
        )["stdout"]
        if str(observed).strip() != str(policy):
            raise RuntimeError(
                f"{leaf}: requested hash policy {policy}, read back {observed!r}"
            )


def run(resume: bool = False) -> None:
    probes = active_gateway_probes()
    if probes:
        raise RuntimeError(
            "gateway probe active; refusing E5 traffic: " + "; ".join(probes)
        )
    intent = load_intent()
    hosts = rail_a_hosts(intent)
    uplinks = leaf_uplinks(intent)
    leaves = sorted(uplinks)
    existing_results: dict[str, Any] | None = None
    if resume:
        if not RESULT_PATH.is_file():
            raise RuntimeError(f"cannot resume: missing {RESULT_PATH}")
        existing_results = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        if existing_results.get("label") != (
            "EMULATED Linux/veth fabric; supplemental RDMA is SOFT-ROCE"
        ):
            raise RuntimeError("cannot resume E5 results with an unexpected label")
    results: dict[str, Any] = existing_results or {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "label": "EMULATED Linux/veth fabric; supplemental RDMA is SOFT-ROCE",
        "runtime": "containerlab 0.78.2 with Podman",
        "iperf3_version": node_result("host1", "iperf3 --version")["stdout"].splitlines()[0],
        "hosts": hosts,
        "uplinks": uplinks,
        "hash_policy": {
            "0": "L3, Linux net.ipv4.fib_multipath_hash_policy=0",
            "1": "L4, Linux net.ipv4.fib_multipath_hash_policy=1",
        },
        "prediction": {
            "tcp_ring": (
                "L3 keeps all N streams of each fixed source/destination pair on "
                "one uplink; L4 gives 1-flow no choice, 4 flows can remain lumpy "
                "(E1 saw 50/50 to about 75/25), and 16 flows should tend closer "
                "to even."
            ),
            "tcp_all_to_all": (
                "Different IP pairs can hash onto different paths even with L3; "
                "within each pair, L3 still cannot distinguish parallel streams. "
                "L4 should improve aggregate sharing as N grows, but is not "
                "predicted to guarantee an even split."
            ),
            "soft_roce": (
                "The two VM endpoints allow parallel QPs; L3 should keep fixed-IP "
                "QP traffic on one spine, while L4 may spread UDP source ports. "
                "Perftest exposes aggregate bandwidth; its equal-share per-QP "
                "number is a derived mean, not a directly measured per-QP rate."
            ),
        },
        "method": {
            "tcp_bytes_per_flow": BYTES_PER_FLOW,
            "tcp_duration_seconds": TCP_DURATION_SECONDS,
            "tcp_command_template": (
                "iperf3 -c <destination> -B <source> -p <unique-port> "
                f"-P <flows-per-pair> -t {TCP_DURATION_SECONDS} --json"
            ),
            "repeats": REPEATS,
            "counter_command": UPLINK_COUNTER_COMMAND,
            "active_gateway_probe_check": "pgrep -af probe_ (via fabric.experiments.e1.active_gateway_probes)",
            "imbalance_implied_bound_definition": (
                "MODEL: observed slowest-flow completion / worst active-leaf "
                "max/mean byte ratio; restates imbalance, not independent "
                "evidence (see E5 'Correction')"
            ),
            "rdma_size_bytes": RDMA_SIZE_BYTES,
            "rdma_iterations_per_qp": RDMA_ITERATIONS,
        },
        "preflight_diagnostics": [
            {
                "label": "EMULATED; parallel byte-count semantics pilot",
                "command": (
                    "timeout 20 iperf3 -c 10.210.0.10 -B 10.210.0.2 "
                    "-p 5480 -P 4 -n 4194304 --json"
                ),
                "context": "first host1->host3 pair of the ring/four-stream cell",
                "received_bytes_stream_1": 1_441_792,
                "assumed_bytes_per_stream": 4_194_304,
                "action": "iperf3 -n was a per-test byte budget, not a per-stream budget",
            },
            {
                "label": "EMULATED; isolated same-leaf path diagnostic",
                "command": (
                    "iperf3 -c 10.210.0.6 -B 10.210.0.2 -p 5901 "
                    "-P 1 -n 4194304 --json"
                ),
                "received_bytes": 4_194_304,
                "elapsed_seconds": 1.001392,
                "received_bits_per_second": 33_507_789.157492768,
            },
            {
                "label": "EMULATED; parallel byte-count semantics confirmation",
                "command": (
                    "timeout 20 iperf3 -c 10.210.0.10 -B 10.210.0.2 "
                    "-p 5480 -P 4 -n 1048576 --json"
                ),
                "context": "first host1->host3 pair of the ring/four-stream cell",
                "received_bytes_stream_1": 393_216,
                "assumed_bytes_per_stream": 1_048_576,
                "action": "replace byte-count mode with fixed-duration runs and interval-derived time-to-target",
            },
            {
                "label": "EMULATED; isolated all-to-all/one-flow diagnostic",
                "command": (
                    "iperf3 -c 10.210.0.6 -B 10.210.0.2 -p 6600 "
                    "-P 1 -n 1048576 --json"
                ),
                "job_time_seconds": 2.620928226994721,
                "wall_seconds": 4.037921365990769,
            },
            {
                "label": "EMULATED; fixed-duration ring/four-stream pilot",
                "command_template": (
                    "iperf3 -c <destination> -B <source> -p <unique-port> "
                    "-P 4 -t 5 --json"
                ),
                "flows_observed": 16,
                "minimum_received_bytes": 1_334_181_888,
                "bytes_per_flow_job_target": BYTES_PER_FLOW,
                "job_time_seconds": 0.8775312490380683,
                "wall_seconds": 7.088074588013114,
                "raw_result": "fabric/experiments/e5-ring4-pilot.json",
            },
        ],
        "tcp_runs": [],
        "roce_runs": [],
        "failures": [],
    }
    results["completed_at"] = None
    results["restored_hash_policy"] = None
    results["status"] = "running"
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    completed_tcp = {
        (record["hash_policy"], record["pattern"], record["flows_per_pair"], record["repeat"])
        for record in results["tcp_runs"]
    }
    completed_roce = {
        (record["hash_policy"], record["qps"], record["repeat"])
        for record in results["roce_runs"]
    }
    cell_number = 0
    completed = False
    try:
        for policy in POLICIES:
            set_hash_policy(leaves, policy)
            for pattern in PATTERNS:
                for flows in FLOW_COUNTS:
                    for repeat in range(1, REPEATS + 1):
                        cell_number += 1
                        key = (policy, pattern, flows, repeat)
                        if key in completed_tcp:
                            continue
                        record = None
                        for attempt in range(1, 3):
                            try:
                                duration_seconds = (
                                    4 if pattern == "all-to-all" and flows == 16
                                    else TCP_DURATION_SECONDS
                                )
                                record = run_tcp_cell(
                                    hosts,
                                    uplinks,
                                    pattern,
                                    flows,
                                    repeat,
                                    cell_number,
                                    duration_seconds,
                                )
                            except RuntimeError as error:
                                failure = {
                                    "transport": "TCP",
                                    "hash_policy": policy,
                                    "pattern": pattern,
                                    "flows_per_pair": flows,
                                    "repeat": repeat,
                                    "attempt": attempt,
                                    "error": str(error),
                                }
                                results["failures"].append(failure)
                                RESULT_PATH.write_text(
                                    json.dumps(results, indent=2) + "\n", encoding="utf-8"
                                )
                                if attempt == 2:
                                    raise
                                print(json.dumps({
                                    "retrying_after_failure": failure
                                }, sort_keys=True))
                                time.sleep(1)
                            else:
                                break
                        if record is None:
                            raise RuntimeError(
                                f"no E5 result for policy={policy}, pattern={pattern}, "
                                f"flows={flows}, repeat={repeat}"
                            )
                        record["hash_policy"] = policy
                        if record["wall_seconds"] > 10:
                            raise RuntimeError(
                                f"E5 TCP cell exceeded 10 seconds: "
                                f"policy={policy}, pattern={pattern}, "
                                f"flows={flows}, repeat={repeat}, "
                                f"wall={record['wall_seconds']:.3f}"
                            )
                        results["tcp_runs"].append(record)
                        completed_tcp.add(key)
                        RESULT_PATH.write_text(
                            json.dumps(results, indent=2) + "\n", encoding="utf-8"
                        )
                        print(json.dumps({
                            "transport": "TCP",
                            "policy": policy,
                            "pattern": pattern,
                            "flows": flows,
                            "repeat": repeat,
                            "job_time_seconds": record["job_time_seconds"],
                            "worst_imbalance": (
                                record["uplink_summary"]["worst_active_leaf_imbalance"]
                            ),
                        }, sort_keys=True))
            for qps in FLOW_COUNTS:
                for repeat in range(1, REPEATS + 1):
                    key = (policy, qps, repeat)
                    if key in completed_roce:
                        continue
                    record = run_roce_cell(uplinks, policy, qps, repeat)
                    if record["job_time_seconds"] > 10:
                        raise RuntimeError(
                            f"E5 SOFT-ROCE cell exceeded 10 seconds: "
                            f"policy={policy}, qps={qps}, repeat={repeat}, "
                            f"wall={record['job_time_seconds']:.3f}"
                        )
                    results["roce_runs"].append(record)
                    completed_roce.add(key)
                    RESULT_PATH.write_text(
                        json.dumps(results, indent=2) + "\n", encoding="utf-8"
                    )
                    print(json.dumps({
                        "transport": "SOFT-ROCE",
                        "policy": policy,
                        "qps": qps,
                        "repeat": repeat,
                        "aggregate_gbps": record["aggregate_gbps"],
                        "source_ports": record["distinct_udp_source_ports"],
                        "worst_imbalance": (
                            record["uplink_summary"]["worst_active_leaf_imbalance"]
                        ),
                    }, sort_keys=True))
        completed = True
    finally:
        set_hash_policy(leaves, 0)
        results["restored_hash_policy"] = 0
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        results["status"] = "complete" if completed else "partial"
        RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(results['tcp_runs'])} TCP and "
        f"{len(results['roce_runs'])} SOFT-ROCE runs to {RESULT_PATH}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip successful cells already recorded in e5-results.json",
    )
    run(resume=parser.parse_args().resume)
