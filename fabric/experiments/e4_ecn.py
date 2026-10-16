"""E4: intent-scaled RED/ECN on an EMULATED leaf-to-spine link.

Run with ``python -m fabric.experiments.e4_ecn``. Captures and raw measurements
are stored under fabric/experiments/e4/ and e4-results.json.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.experiments.e3.bth_decode import decode, l3_offset, pcap_records
from fabric.experiments.e3.run import background, finish, finish_capture, perftest, text
from fabric.experiments.e3.run import endpoints as e3_endpoints
from fabric.intent.schema.validate import load_intent
from fabric.tests.lab import node_result

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e4-results.json"
CAPTURE_DIR = ROOT / "fabric" / "experiments" / "e4"
LEAF = "leaf1"
EGRESS = "eth2"
TAP = "spine2-tap"
TAP_INTERFACE = "eth1"
SOURCE = "vmhost1"
DESTINATION = "vmhost2"
DURATION = 5
IPERF_PORT = 5217
RED_RATE_MBIT = 500
RED_AVPKT_BYTES = 1500
CAPTURE_LIMIT = 1200
CAPTURE_SNAPLEN = 128
PROBE_PATTERN = "probe_p8|probe_p1|capacity|probe_"


def refuse_active_gateway_probes() -> None:
    result = subprocess.run(
        ["pgrep", "-af", PROBE_PATTERN],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return
    if result.returncode != 0:
        raise RuntimeError(
            f"pgrep failed with exit {result.returncode}: {result.stderr}"
        )
    raise RuntimeError(
        "gateway probe active; refusing to load the fabric: "
        + "; ".join(result.stdout.splitlines())
    )


def checked_text(node: str, command: str) -> str:
    result = node_result(node, command)
    stdout = result["stdout"]
    return stdout if isinstance(stdout, str) else json.dumps(stdout)


def scaled_red_parameters(intent: dict[str, Any], rate_mbit: int) -> dict[str, int | float]:
    """Scale intent byte thresholds by the emulated/hardware port-rate ratio."""
    if rate_mbit <= 0:
        raise ValueError("RED rate must be positive")
    qos = intent["qos"]
    hardware_mbit = int(qos["target"]["port_speed_gbps"]) * 1000
    ecn = qos["ecn"]
    scale = rate_mbit / hardware_mbit
    scaled_minimum = max(1, round(int(ecn["kmin_bytes"]) * scale))
    minimum = max(RED_AVPKT_BYTES, scaled_minimum)
    maximum = max(minimum * 2, round(int(ecn["kmax_bytes"]) * scale))
    burst = max(1, int((2 * minimum + maximum) / (3 * RED_AVPKT_BYTES)))
    limit = max(maximum + burst * RED_AVPKT_BYTES + 1, 4 * maximum)
    return {
        "hardware_rate_mbit": hardware_mbit,
        "emulated_rate_mbit": rate_mbit,
        "scale": scale,
        "unclamped_min_bytes": scaled_minimum,
        "minimum_packet_floor_bytes": RED_AVPKT_BYTES,
        "min_bytes": minimum,
        "max_bytes": maximum,
        "max_probability": int(ecn["pmax_percent"]) / 100,
        "avpkt_bytes": RED_AVPKT_BYTES,
        "burst_packets": burst,
        "limit_bytes": limit,
    }


def install_bottleneck(parameters: dict[str, int | float]) -> list[str]:
    leaf_commands = [
        f"tc qdisc replace dev {EGRESS} root handle 1: "
        f"tbf rate {RED_RATE_MBIT}mbit burst 64kb latency 50ms",
        f"tc qdisc replace dev {EGRESS} parent 1:1 handle 10: red "
        f"limit {parameters['limit_bytes']} "
        f"min {parameters['min_bytes']} max {parameters['max_bytes']} "
        f"avpkt {parameters['avpkt_bytes']} burst {parameters['burst_packets']} "
        f"bandwidth {RED_RATE_MBIT}mbit "
        f"probability {parameters['max_probability']} ecn",
    ]
    for command in leaf_commands:
        checked_text(LEAF, command)
    return leaf_commands


def guest_sysctl(value: int) -> None:
    for guest in (SOURCE, DESTINATION):
        checked_text(
            guest,
            f"vm-exec sudo -n /usr/sbin/sysctl -w net.ipv4.tcp_ecn={value}",
        )


def qdisc_stats() -> str:
    return checked_text(LEAF, f"tc -s qdisc show dev {EGRESS}")


def start_capture(tag: str, packet_filter: str) -> tuple[subprocess.Popen[str], str]:
    capture_path = f"/tmp/e4-{tag}-{time.time_ns()}.pcap"
    command = (
        f"timeout 12 tcpdump -n -i {TAP_INTERFACE} -s {CAPTURE_SNAPLEN} "
        f"-c {CAPTURE_LIMIT} -w {capture_path} '{packet_filter}'"
    )
    process = background(TAP, command)
    time.sleep(0.3)
    return process, capture_path


def save_capture(tag: str, remote_path: str, process: subprocess.Popen[str]) -> dict[str, Any]:
    result = finish_capture(TAP, process)
    encoded = text(TAP, f"base64 -w0 {remote_path}").strip()
    raw = base64.b64decode(encoded, validate=True)
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = CAPTURE_DIR / f"{tag}.pcap"
    local_path.write_bytes(raw)
    text(TAP, f"rm -f -- {remote_path}")
    return {
        "file": str(local_path.relative_to(ROOT)),
        "bytes": len(raw),
        "tcpdump_return_code": result["return-code"],
        "tcpdump_stdout": result["stdout"],
        "tcpdump_stderr": result["stderr"],
    }


def parse_ping(output: str) -> dict[str, float | int | None]:
    match = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", output)
    rtt = re.search(r"(?:rtt|round-trip).* = ([0-9.]+)/([0-9.]+)/([0-9.]+)", output)
    return {
        "transmitted": int(match.group(1)) if match else 0,
        "received": int(match.group(2)) if match else 0,
        "rtt_min_ms": float(rtt.group(1)) if rtt else None,
        "rtt_avg_ms": float(rtt.group(2)) if rtt else None,
        "rtt_max_ms": float(rtt.group(3)) if rtt else None,
    }


def parse_tcp_fields(raw: bytes) -> dict[str, Any]:
    packets: list[dict[str, int]] = []
    for linktype, frame in pcap_records(raw):
        offset = l3_offset(linktype, frame)
        if offset is None or len(frame) < offset + 20 or frame[offset + 9] != 6:
            continue
        tcp_offset = offset + (frame[offset] & 0x0F) * 4
        if len(frame) < tcp_offset + 14:
            continue
        tcp_flags = frame[tcp_offset + 13]
        packets.append({
            "dscp": frame[offset + 1] >> 2,
            "ecn": frame[offset + 1] & 0x03,
            "ece": int(bool(tcp_flags & 0x40)),
            "cwr": int(bool(tcp_flags & 0x80)),
        })
    return {
        "packets": len(packets),
        "ecn_bits": {
            str(value): sum(packet["ecn"] == value for packet in packets)
            for value in range(4)
        },
        "dscp_values": dict(
            (str(dscp), sum(packet["dscp"] == dscp for packet in packets))
            for dscp in sorted({packet["dscp"] for packet in packets})
        ),
        "tcp_ece_packets": sum(packet["ece"] for packet in packets),
        "tcp_cwr_packets": sum(packet["cwr"] for packet in packets),
    }


def parse_roce_capture(raw: bytes) -> dict[str, Any]:
    packets = [
        packet
        for linktype, frame in pcap_records(raw)
        if (packet := decode(frame, linktype)) is not None
    ]
    return {
        "packets": len(packets),
        "ecn_bits": {
            str(value): sum(packet["ecn"] == value for packet in packets)
            for value in range(4)
        },
        "opcodes": {
            f"0x{opcode:02x}": count
            for opcode, count in sorted(Counter(packet["opcode"] for packet in packets).items())
        },
        "cnp_packets": sum(packet["opcode"] == 0x81 for packet in packets),
    }


def run_tcp_condition(
    condition: str,
    ecn_sysctl: int,
    tos: int,
    repeat: int,
) -> dict[str, Any]:
    guest_sysctl(ecn_sysctl)
    before = qdisc_stats()
    capture, remote_path = start_capture(
        f"tcp-{condition}-r{repeat}",
        f"host 10.210.0.18 and host 10.210.0.22 and tcp",
    )
    ping = background(
        SOURCE,
        "ping -n -I 10.210.0.18 -i 0.1 -c 50 10.210.0.22",
    )
    server = background(
        DESTINATION,
        f"timeout 20 iperf3 -s -1 -p {IPERF_PORT}",
    )
    time.sleep(0.5)
    command = (
        f"iperf3 -c 10.210.0.22 -B 10.210.0.18 -p {IPERF_PORT} "
        f"-P 4 -t {DURATION} --tos {tos} --json"
    )
    client_text = checked_text(SOURCE, f"vm-exec {command}")
    client = json.loads(client_text)
    finish(DESTINATION, server)
    ping_text = finish(SOURCE, ping)
    capture_meta = save_capture(
        f"tcp-{condition}-r{repeat}", remote_path, capture
    )
    raw = (ROOT / capture_meta["file"]).read_bytes()
    after = qdisc_stats()
    received = client["end"]["sum_received"]
    return {
        "condition": condition,
        "repeat": repeat,
        "sysctl_tcp_ecn": ecn_sysctl,
        "tos": tos,
        "command": command,
        "duration_seconds": DURATION,
        "received_bytes": received["bytes"],
        "received_gbps": received["bits_per_second"] / 1e9,
        "iperf3_json": client,
        "ping": parse_ping(ping_text),
        "ping_output": ping_text,
        "qdisc_before": before,
        "qdisc_after": after,
        "capture": capture_meta,
        "captured_ip_fields": parse_tcp_fields(raw),
    }


def run_roce() -> dict[str, Any]:
    guest_sysctl(0)
    before = qdisc_stats()
    capture_path = f"/tmp/e4-roce-{time.time_ns()}.pcap"
    capture = background(
        TAP,
        f"timeout 15 tcpdump -n -i {TAP_INTERFACE} -s 256 -c 1200 "
        f"-w {capture_path} 'udp port 4791'",
    )
    time.sleep(0.3)
    endpoints = e3_endpoints()
    result = perftest(
        "ib_write_bw",
        endpoints["vmhost1:A"],
        endpoints["vmhost2:A"],
        65536,
        extra="--tclass 106",
    )
    capture_result = finish_capture(TAP, capture)
    encoded = text(TAP, f"base64 -w0 {capture_path}").strip()
    raw = base64.b64decode(encoded, validate=True)
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = CAPTURE_DIR / "roce-tclass106.pcap"
    local_path.write_bytes(raw)
    text(TAP, f"rm -f -- {capture_path}")
    after = qdisc_stats()
    return {
        "label": "SOFT-ROCE over EMULATED fabric",
        "command": result["client_command"],
        "parsed": result["parsed"],
        "client_output": result["client_output"],
        "server_command": result["server_command"],
        "server_output_tail": result["server_output_tail"],
        "mpstat": result["mpstat"],
        "qdisc_before": before,
        "qdisc_after": after,
        "capture": {
            "file": str(local_path.relative_to(ROOT)),
            "bytes": len(raw),
            "tcpdump_return_code": capture_result["return-code"],
            "tcpdump_stdout": capture_result["stdout"],
            "tcpdump_stderr": capture_result["stderr"],
        },
        "decoded": parse_roce_capture(raw),
    }


def run() -> None:
    refuse_active_gateway_probes()
    intent = load_intent()
    parameters = scaled_red_parameters(intent, RED_RATE_MBIT)
    results: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "label": "EMULATED; RoCE segment separately labeled SOFT-ROCE",
        "intent": {
            "hardware_target_gbps": intent["qos"]["target"]["port_speed_gbps"],
            "ecn": intent["qos"]["ecn"],
            "pfc": intent["qos"]["pfc"],
        },
        "source": {"host": SOURCE, "ip": "10.210.0.18"},
        "destination": {"host": DESTINATION, "ip": "10.210.0.22"},
        "bottleneck": {
            "leaf": LEAF,
            "egress_interface": EGRESS,
            "spine_tap": TAP,
            "tap_interface": TAP_INTERFACE,
            "red_parameters_rendered_from_intent": parameters,
            "commands": [],
        },
        "prediction": {
            "tcp_ecn_on": "RED should set CE on ECT(0) packets; TCP should report ECE and CWR and maintain a usable rate.",
            "tcp_ecn_off": "Not-ECT traffic should be dropped above RED Kmin; throughput should be lower or less stable, with no CE/ECE/CWR response.",
            "soft_roce": (
                "The 1 Gbit/s calibration carried 0.62 Gbit/s and did not mark; "
                "at 500 Mbit/s, expect RED CE on SOFT-ROCE packets, no CNP "
                "(BTH opcode 0x81), and no sender-rate reaction."
            ),
            "pfc": (
                "There is no PFC in this veth lab; effective scaled ECN Kmax is "
                f"{parameters['max_bytes']:,} B, before the scaled XOFF design "
                f"threshold of {round(intent['qos']['pfc']['xoff_threshold_bytes'] * parameters['scale']):,} B."
            ),
        },
        "tcp_runs": [],
    }
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    try:
        results["bottleneck"]["commands"] = install_bottleneck(parameters)
        for condition, sysctl_value, tos in (
            ("ecn-on", 1, 106),
            ("ecn-off", 0, 104),
        ):
            for repeat in range(1, 4):
                record = run_tcp_condition(
                    condition, sysctl_value, tos, repeat
                )
                results["tcp_runs"].append(record)
                RESULT_PATH.write_text(
                    json.dumps(results, indent=2) + "\n", encoding="utf-8"
                )
                print(json.dumps({
                    "condition": condition,
                    "repeat": repeat,
                    "received_gbps": record["received_gbps"],
                    "rtt_avg_ms": record["ping"]["rtt_avg_ms"],
                    "captured_ip_fields": record["captured_ip_fields"],
                }, sort_keys=True))
        results["roce"] = run_roce()
        RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    finally:
        checked_text(LEAF, f"tc qdisc del dev {EGRESS} root")
        guest_sysctl(2)
    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote E4 results to {RESULT_PATH}")


if __name__ == "__main__":
    run()
