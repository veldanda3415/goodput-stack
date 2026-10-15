from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fabric.intent.schema.validate import load_intent
from fabric.tests.lab import node_json, node_result


ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e1-results.json"
PROBE_PATTERN = "probe_p8|probe_p1|capacity|probe_"
FLOW_COUNTS = (1, 4, 32)
REPEATS = 3
DURATION_SECONDS = 10


def active_gateway_probes() -> list[str]:
    result = subprocess.run(
        ["pgrep", "-af", PROBE_PATTERN],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        raise RuntimeError(f"pgrep failed with exit {result.returncode}: {result.stderr}")
    return result.stdout.splitlines()


def wait_for_gateway_probes() -> int:
    waited = 0
    while active := active_gateway_probes():
        if waited >= 20 * 60:
            raise RuntimeError(
                "gateway probe still running after 20 minutes; refusing to start iperf3: "
                + "; ".join(active)
            )
        print(f"Gateway probe active; waiting 60 seconds: {active}")
        time.sleep(60)
        waited += 60
    return waited


def link_tx_bytes(node: str, interface: str) -> int:
    links = node_json(node, f"ip -j -s link show dev {interface}")
    if len(links) != 1 or "stats64" not in links[0]:
        raise RuntimeError(f"missing byte counters for {node}:{interface}: {links!r}")
    return int(links[0]["stats64"]["tx"]["bytes"])


def start_iperf_server(server: str) -> subprocess.Popen[str]:
    intent = load_intent()
    return subprocess.Popen(
        [
            "containerlab", "exec", "--runtime", "podman",
            "--name", intent["name"],
            "--label", f"clab-node-name={server}",
            "--format", "json", "--log-level", "error",
            "--cmd", "timeout 25s iperf3 -s -1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def finish_iperf_server(server: str, process: subprocess.Popen[str]) -> None:
    stdout, stderr = process.communicate(timeout=DURATION_SECONDS + 20)
    if process.returncode != 0:
        raise RuntimeError(
            f"containerlab exec failed for iperf3 server on {server}: "
            f"exit={process.returncode}; stdout={stdout!r}; stderr={stderr!r}"
        )
    container = f"clab-{load_intent()['name']}-{server}"
    result = json.loads(stdout)[container][0]
    if result["return-code"] != 0:
        raise RuntimeError(
            f"iperf3 server failed on {server}: "
            f"exit={result['return-code']}; stdout={result['stdout']!r}; "
            f"stderr={result['stderr']!r}"
        )


def run_iperf(
    client: str,
    server: str,
    source_ip: str,
    target_ip: str,
    flows: int,
) -> dict[str, Any]:
    server_process = start_iperf_server(server)
    time.sleep(0.5)
    if server_process.poll() is not None:
        finish_iperf_server(server, server_process)
        raise RuntimeError(f"one-shot iperf3 server exited before client start on {server}")
    command = (
        f"iperf3 -c {target_ip} -B {source_ip} -P {flows} "
        f"-t {DURATION_SECONDS} --json"
    )
    result = node_result(client, command)
    client_output = result["stdout"]
    if isinstance(client_output, dict):
        client_json = client_output
    elif isinstance(client_output, str):
        try:
            client_json = json.loads(client_output)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"iperf3 returned invalid JSON for {command}: {client_output!r}"
            ) from error
    else:
        raise RuntimeError(
            f"iperf3 returned unexpected output for {command}: {client_output!r}"
        )

    finish_iperf_server(server, server_process)

    sent = client_json["end"]["sum_sent"]
    received = client_json["end"]["sum_received"]
    return {
        "command": command,
        "sent_bytes": sent["bytes"],
        "sent_bits_per_second": sent["bits_per_second"],
        "received_bytes": received["bytes"],
        "received_bits_per_second": received["bits_per_second"],
    }


def host_for_rail(intent: dict[str, Any], leaf: str, rail: str) -> tuple[str, dict[str, Any]]:
    matches = [
        (host["name"], nic)
        for host in intent["hosts"]
        for nic in host["nics"]
        if nic["leaf"] == leaf and nic["rail"] == rail
    ]
    if not matches:
        raise RuntimeError(f"no {rail} host attachment on {leaf}")
    return sorted(matches, key=lambda item: item[0])[0]


def run() -> None:
    intent = load_intent()
    source_host, source_nic = host_for_rail(intent, "leaf1", "A")
    target_host, target_nic = host_for_rail(intent, "leaf2", "A")
    source_ip = source_nic["address"].split("/")[0]
    target_ip = target_nic["address"].split("/")[0]
    leaves = [node["name"] for node in intent["nodes"] if node["role"] == "leaf"]
    uplinks = sorted(
        endpoint["interface"]
        for link in intent["links"]
        if link["kind"] == "fabric"
        for endpoint in (link["a"], link["b"])
        if endpoint["node"] == "leaf1"
    )
    if len(uplinks) != intent["ecmp_width"]:
        raise RuntimeError(f"leaf1 has {len(uplinks)} uplinks; expected ECMP width {intent['ecmp_width']}")

    version = node_result(source_host, "iperf3 --version")["stdout"].splitlines()[0]
    results: dict[str, Any] = {
        "started_at": datetime.now().astimezone().isoformat(),
        "label": "EMULATED",
        "runtime": "containerlab with Podman",
        "images": intent["images"],
        "kernel_release": node_result("leaf1", "uname -r")["stdout"].strip(),
        "duration_seconds": DURATION_SECONDS,
        "repeats": REPEATS,
        "iperf3_version": version,
        "source": {"host": source_host, "ip": source_ip, "rail": "A"},
        "target": {"host": target_host, "ip": target_ip, "rail": "A"},
        "source_leaf": "leaf1",
        "counter_command": "ip -j -s link show dev <uplink> (tx.bytes before/after)",
        "uplinks": uplinks,
        "runs": [],
    }
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    for policy in (0, 1):
        for leaf in leaves:
            node_result(leaf, f"sysctl -w net.ipv4.fib_multipath_hash_policy={policy}")
            observed = node_result(
                leaf, "sysctl -n net.ipv4.fib_multipath_hash_policy"
            )["stdout"]
            if str(observed).strip() != str(policy):
                raise RuntimeError(
                    f"{leaf}: requested hash policy {policy}, read back {observed!r}"
                )

        for flows in FLOW_COUNTS:
            for repeat in range(1, REPEATS + 1):
                probe_wait = wait_for_gateway_probes()
                before = {interface: link_tx_bytes("leaf1", interface) for interface in uplinks}
                iperf = run_iperf(
                    source_host,
                    target_host,
                    source_ip,
                    target_ip,
                    flows,
                )
                after = {interface: link_tx_bytes("leaf1", interface) for interface in uplinks}
                deltas = {
                    interface: after[interface] - before[interface]
                    for interface in uplinks
                }
                total = sum(deltas.values())
                if total <= 0 or any(delta < 0 for delta in deltas.values()):
                    raise RuntimeError(
                        f"invalid uplink byte deltas for policy={policy}, "
                        f"flows={flows}, repeat={repeat}: {deltas!r}"
                    )
                record = {
                    "policy": policy,
                    "flows": flows,
                    "repeat": repeat,
                    "gateway_probe_wait_seconds": probe_wait,
                    "counter_before_tx_bytes": before,
                    "counter_after_tx_bytes": after,
                    "counter_delta_tx_bytes": deltas,
                    "counter_delta_tx_percent": {
                        interface: round(100 * deltas[interface] / total, 2)
                        for interface in uplinks
                    },
                    **iperf,
                }
                results["runs"].append(record)
                RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(record, sort_keys=True))

    for leaf in leaves:
        node_result(leaf, "sysctl -w net.ipv4.fib_multipath_hash_policy=0")
    results["restored_hash_policy"] = 0
    results["completed_at"] = datetime.now().astimezone().isoformat()
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(results['runs'])} runs to {RESULT_PATH}")


if __name__ == "__main__":
    run()
