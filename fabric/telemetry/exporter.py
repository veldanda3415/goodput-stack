"""Prometheus exporter for Linux counters from the EMULATED containerlab fabric."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from fabric.intent.schema.validate import load_intent
from fabric.tests.lab import node_json, node_result


def metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def metric_line(name: str, value: int | float, **labels: str) -> str:
    label_text = ""
    if labels:
        label_text = "{" + ",".join(
            f'{key}="{metric_label(val)}"' for key, val in sorted(labels.items())
        ) + "}"
    return f"{name}{label_text} {value}"


def json_output(node: str, command: str) -> Any:
    result = node_result(node, command)["stdout"]
    if isinstance(result, (dict, list)):
        return result
    if not isinstance(result, str):
        raise RuntimeError(f"unexpected output from {node}: {result!r}")
    try:
        return json.loads(result)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"invalid JSON from {node} for {command}: {result!r}"
        ) from error


def state_records(value: Any, state_fields: tuple[str, ...]) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []

    def visit(item: Any, path: str = "") -> None:
        if isinstance(item, dict):
            for field in state_fields:
                state = item.get(field)
                if isinstance(state, str):
                    name = item.get("hostname") or item.get("peer")
                    records.append((
                        str(name) if name else path.rsplit("/", 1)[-1],
                        state,
                    ))
                    break
            for key, child in item.items():
                visit(child, f"{path}/{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}/{index}")

    visit(value)
    return records


def qdisc_counters(value: Any) -> dict[str, int]:
    counters: dict[str, int] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"marked", "prob_mark", "forced_mark"} and isinstance(child, int):
                    counters["marked"] = counters.get("marked", 0) + child
                elif key in {"early", "pdrop"} and isinstance(child, int):
                    counters[key] = counters.get(key, 0) + child
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return counters


def topology() -> tuple[dict[str, list[str]], list[str]]:
    intent = load_intent()
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
    for interfaces in uplinks.values():
        interfaces.sort()
    return uplinks, [node["name"] for node in intent["nodes"]]


def collect_metrics() -> str:
    uplinks, routers = topology()
    lines = [
        "# HELP fabric_interface_tx_bytes_total EMULATED interface transmit bytes.",
        "# TYPE fabric_interface_tx_bytes_total counter",
        "# HELP fabric_interface_rx_bytes_total EMULATED interface receive bytes.",
        "# TYPE fabric_interface_rx_bytes_total counter",
        "# HELP fabric_interface_tx_dropped_total EMULATED interface transmit drops.",
        "# TYPE fabric_interface_tx_dropped_total counter",
        "# HELP fabric_interface_rx_dropped_total EMULATED interface receive drops.",
        "# TYPE fabric_interface_rx_dropped_total counter",
        "# HELP fabric_interface_tx_errors_total EMULATED interface transmit errors.",
        "# TYPE fabric_interface_tx_errors_total counter",
        "# HELP fabric_interface_rx_errors_total EMULATED interface receive errors.",
        "# TYPE fabric_interface_rx_errors_total counter",
        "# HELP fabric_qdisc_ecn_marked_packets_total Linux qdisc ECN marks when available.",
        "# TYPE fabric_qdisc_ecn_marked_packets_total counter",
        "# HELP fabric_qdisc_early_drops_total Linux qdisc early drops when available.",
        "# TYPE fabric_qdisc_early_drops_total counter",
        "# HELP fabric_qdisc_probability_drops_total Linux qdisc probability drops when available.",
        "# TYPE fabric_qdisc_probability_drops_total counter",
        "# HELP fabric_bgp_neighbor_established BGP neighbor established state on FRR nodes.",
        "# TYPE fabric_bgp_neighbor_established gauge",
        "# HELP fabric_bfd_peer_up BFD peer state on FRR nodes.",
        "# TYPE fabric_bfd_peer_up gauge",
    ]

    for leaf, interfaces in uplinks.items():
        links = json_output(leaf, "ip -j -s link show")
        by_name = {link.get("ifname"): link for link in links}
        for interface in interfaces:
            link = by_name.get(interface)
            if not link or "stats64" not in link:
                raise RuntimeError(f"missing counters for {leaf}:{interface}")
            for direction in ("tx", "rx"):
                stats = link["stats64"][direction]
                lines.append(metric_line(
                    f"fabric_interface_{direction}_bytes_total",
                    int(stats["bytes"]),
                    node=leaf,
                    interface=interface,
                ))
                drop_name = (
                    "fabric_interface_tx_dropped_total"
                    if direction == "tx"
                    else "fabric_interface_rx_dropped_total"
                )
                error_name = (
                    "fabric_interface_tx_errors_total"
                    if direction == "tx"
                    else "fabric_interface_rx_errors_total"
                )
                lines.append(metric_line(
                    drop_name, int(stats["dropped"]), node=leaf, interface=interface
                ))
                lines.append(metric_line(
                    error_name, int(stats["errors"]), node=leaf, interface=interface
                ))
            qdisc = json_output(
                leaf, f"tc -s -j qdisc show dev {interface}"
            )
            for counter, value in qdisc_counters(qdisc).items():
                name = {
                    "marked": "fabric_qdisc_ecn_marked_packets_total",
                    "early": "fabric_qdisc_early_drops_total",
                    "pdrop": "fabric_qdisc_probability_drops_total",
                }[counter]
                lines.append(metric_line(name, value, node=leaf, interface=interface))

    for router in routers:
        bgp = json_output(router, "vtysh -c 'show bgp summary json'")
        for neighbor, state in state_records(bgp, ("state", "peerState")):
            lines.append(metric_line(
                "fabric_bgp_neighbor_established",
                int(state.lower() == "established"),
                node=router,
                neighbor=neighbor,
            ))
        bfd = json_output(router, "vtysh -c 'show bfd peers json'")
        for peer, state in state_records(bfd, ("status", "state")):
            lines.append(metric_line(
                "fabric_bfd_peer_up",
                int(state.lower() in {"up", "ok"}),
                node=router,
                peer=peer,
            ))
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/metrics":
            self.send_error(404)
            return
        try:
            body = collect_metrics().encode()
        except (AssertionError, KeyError, RuntimeError, TypeError, ValueError, OSError) as error:
            self.send_error(500, explain=str(error))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        if os.environ.get("FABRIC_TELEMETRY_ACCESS_LOG") == "1":
            super().log_message(format, *args)


def main() -> None:
    address = os.environ.get("FABRIC_TELEMETRY_ADDRESS", "127.0.0.1")
    port = int(os.environ.get("FABRIC_TELEMETRY_PORT", "9109"))
    ThreadingHTTPServer((address, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
