"""Render the EMULATED lab shaping profile and even-split pins from intent.

`lab_shaping` puts a Linux TBF qdisc on both ends of every leaf<->spine veth
so the fabric, not the host containers, is the bottleneck (tc-tbf(8),
https://man7.org/linux/man-pages/man8/tc-tbf.8.html, *PARAMETERS*: rate,
burst, limit). The pin scripts are the measured even-split baseline for E5:
policy rules that send each cross-leaf host pair over an alternating uplink.
FRR's unnumbered BGP installs `169.254.0.1` as a permanent onlink neighbor on
each peer interface, so a pinned route needs no runtime next-hop lookup
(FRR 10.2 BGP docs, "Unnumbered BGP"/RFC 5549:
https://docs.frrouting.org/en/stable-10.2/bgp.html#ipv6-support).
"""
from __future__ import annotations

from typing import Any

PIN_TABLE_BASE = 200
PIN_RULE_PRIORITY = 5000
UNNUMBERED_NEXT_HOP = "169.254.0.1"


def fabric_ports(intent: dict[str, Any]) -> dict[str, list[str]]:
    """Router -> sorted list of its leaf<->spine interfaces."""
    ports: dict[str, list[str]] = {}
    for link in intent["links"]:
        if link["kind"] != "fabric":
            continue
        for endpoint in (link["a"], link["b"]):
            ports.setdefault(endpoint["node"], []).append(endpoint["interface"])
    return {node: sorted(interfaces) for node, interfaces in sorted(ports.items())}


def shape_scripts(intent: dict[str, Any]) -> dict[str, dict[str, str]]:
    """{router: {"on": script, "off": script}} for every fabric port."""
    shaping = intent["lab_shaping"]
    tbf = (
        f"tbf rate {shaping['uplink_rate_mbit']}mbit "
        f"burst {shaping['burst_bytes']} limit {shaping['limit_bytes']}"
    )
    scripts: dict[str, dict[str, str]] = {}
    for node, interfaces in fabric_ports(intent).items():
        on = ["#!/bin/sh", "set -eu"]
        off = ["#!/bin/sh"]
        for interface in interfaces:
            on.append(f"tc qdisc replace dev {interface} root {tbf}")
            off.append(f"tc qdisc del dev {interface} root 2>/dev/null || true")
        scripts[node] = {"on": "\n".join(on) + "\n", "off": "\n".join(off) + "\n"}
    return scripts


def rail_hosts(intent: dict[str, Any], rail: str) -> list[dict[str, str]]:
    out = []
    for host in intent["hosts"]:
        for nic in host["nics"]:
            if nic["rail"] == rail:
                out.append({
                    "name": host["name"],
                    "ip": nic["address"].split("/")[0],
                    "leaf": nic["leaf"],
                })
    return sorted(out, key=lambda item: item["name"])


def collective_pairs(names: list[str], pattern: str) -> list[tuple[str, str]]:
    """Same ordering as fabric.tools.collective_gen.collective_pairs."""
    names = sorted(names)
    if pattern == "ring":
        ordered = (names[0], names[2], names[1], names[3])
        return [(ordered[i], ordered[(i + 1) % len(ordered)]) for i in range(len(ordered))]
    if pattern == "all-to-all":
        return [(s, d) for s in names for d in names if s != d]
    raise ValueError(f"unsupported collective pattern: {pattern}")


def pin_assignment(intent: dict[str, Any], pattern: str) -> dict[str, list[dict[str, str]]]:
    """Leaf -> ordered host pairs it sources, each pinned to one uplink.

    Pins are symmetric: both directions of an unordered host pair use the
    same spine. One-way pins break replies, because Linux reverse-path
    validation on the source leaf consults the same policy rule and drops
    the reply (measured: `nstat TcpExtIPReversePathFilter` +2 per ping).
    The spine per unordered pair is the lexicographically first assignment
    that minimizes the busiest (leaf, uplink) count of pattern pairs.
    """
    rail = intent["lab_shaping"]["pin_rail"]
    hosts = {host["name"]: host for host in rail_hosts(intent, rail)}
    ports = fabric_ports(intent)
    width = intent["ecmp_width"]
    forward = [
        (s, d) for s, d in collective_pairs(list(hosts), pattern)
        if hosts[s]["leaf"] != hosts[d]["leaf"]
    ]
    unordered = sorted({tuple(sorted(pair)) for pair in forward})
    best: tuple[int, tuple[int, ...]] | None = None
    for code in range(width ** len(unordered)):
        choice = tuple((code // width ** i) % width for i in range(len(unordered)))
        load: dict[tuple[str, int], int] = {}
        for s, d in forward:
            spine = choice[unordered.index(tuple(sorted((s, d))))]
            key = (hosts[s]["leaf"], spine)
            load[key] = load.get(key, 0) + 1
        score = max(load.values())
        if best is None or score < best[0]:
            best = (score, choice)
    assert best is not None
    spine_of = dict(zip(unordered, best[1]))
    by_leaf: dict[str, list[dict[str, str]]] = {}
    for pair, spine in spine_of.items():
        for s, d in (pair, pair[::-1]):
            leaf = hosts[s]["leaf"]
            by_leaf.setdefault(leaf, []).append({
                "source": s,
                "destination": d,
                "source_ip": hosts[s]["ip"],
                "destination_ip": hosts[d]["ip"],
                "uplink": ports[leaf][spine],
                "pattern_pair": (s, d) in forward,
            })
    return {leaf: sorted(pins, key=lambda p: (p["source"], p["destination"])) for leaf, pins in sorted(by_leaf.items())}


def pin_scripts(intent: dict[str, Any], pattern: str) -> dict[str, dict[str, str]]:
    """{leaf: {"on": script, "off": script}} for the even-split baseline."""
    scripts: dict[str, dict[str, str]] = {}
    for leaf, interfaces in fabric_ports(intent).items():
        if not any(n["name"] == leaf and n["role"] == "leaf" for n in intent["nodes"]):
            continue
        on = ["#!/bin/sh", "set -eu"]
        off = ["#!/bin/sh"]
        for index, interface in enumerate(interfaces, start=1):
            table = PIN_TABLE_BASE + index
            on.append(
                f"ip route replace default via {UNNUMBERED_NEXT_HOP} dev {interface} "
                f"onlink table {table}"
            )
            off.append(f"ip route flush table {table} 2>/dev/null || true")
        for rule, pin in enumerate(pin_assignment(intent, pattern).get(leaf, []), start=1):
            table = PIN_TABLE_BASE + interfaces.index(pin["uplink"]) + 1
            on.append(
                f"ip rule add priority {PIN_RULE_PRIORITY + rule} from {pin['source_ip']} "
                f"to {pin['destination_ip']} table {table}"
                f"  # {pin['source']}->{pin['destination']} via {pin['uplink']}"
                f"{'' if pin['pattern_pair'] else ' (reverse of a pattern pair)'}"
            )
        off.append(
            f"while ip rule show | grep -q '^{PIN_RULE_PRIORITY // 1000}[0-9][0-9][0-9]:'; do "
            f"ip rule del priority $(ip rule show | awk -F: '/^{PIN_RULE_PRIORITY // 1000}[0-9][0-9][0-9]:/ {{print $1; exit}}'); done"
        )
        scripts[leaf] = {"on": "\n".join(on) + "\n", "off": "\n".join(off) + "\n"}
    return scripts
