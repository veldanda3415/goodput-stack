"""Render front-end EVPN-VXLAN tenancy (symmetric IRB) from intent.

Linux data plane per leaf follows FRR 10.2 "EVPN" -> "Linux Interface
Configuration" (https://docs.frrouting.org/en/stable-10.2/evpn.html): one
VRF device per tenant; an L3VNI VXLAN device in its own bridge whose only
member is the VXLAN device and whose SVI has no IP; one L2VNI bridge + VXLAN
device per local segment with the gateway address on the bridge (SVI);
`local <loopback>` VTEP source, `nolearning`, and bridge-port `learning off`
+ `neigh_suppress on`. Device semantics: ip-link(8) `vxlan`/`vrf` types
(https://man7.org/linux/man-pages/man8/ip-link.8.html) and the kernel VRF
document (https://docs.kernel.org/networking/vrf.html).
"""
from __future__ import annotations

import ipaddress
from typing import Any


def tenant_link_port(intent: dict[str, Any], endpoint: str, leaf: str) -> str:
    for link in intent["links"]:
        if link["kind"] != "tenant":
            continue
        ends = {ep["node"]: ep["interface"] for ep in (link["a"], link["b"])}
        if endpoint in ends and leaf in ends:
            return ends[leaf]
    raise ValueError(f"no tenant link between {endpoint} and {leaf}")


def endpoint_interface(intent: dict[str, Any], endpoint: str) -> str:
    for link in intent["links"]:
        for ep in (link["a"], link["b"]):
            if link["kind"] == "tenant" and ep["node"] == endpoint:
                return ep["interface"]
    raise ValueError(f"no tenant link for {endpoint}")


def leaf_vrfs(intent: dict[str, Any], leaf: str) -> list[dict[str, Any]]:
    """Tenants with a segment on this leaf, with that segment and its ports."""
    if "tenants" not in intent:
        return []
    out = []
    for vrf in intent["tenants"]["vrfs"]:
        segment = next((seg for seg in vrf["segments"] if seg["leaf"] == leaf), None)
        if segment is None:
            continue
        subnet = ipaddress.ip_network(segment["subnet"])
        out.append({
            **vrf,
            "segment": {
                **segment,
                "gateway": f"{subnet.network_address + 1}/{subnet.prefixlen}",
                "ports": [
                    tenant_link_port(intent, ep["name"], leaf)
                    for ep in vrf["endpoints"] if ep["leaf"] == leaf
                ],
            },
        })
    return out


def leaf_tenant_script(intent: dict[str, Any], leaf: str, stage: str = "all") -> str:
    """Tenant data plane for one leaf.

    stage "devices": VRF, bridges, VXLAN devices, SVI addresses. Runs as the
    container command *before* FRR starts, so zebra sees the VRFs when it
    reads `vrf <name> / vni <L3VNI>` (measured: when FRR started first, it
    bound the L3VNI to the default VRF). stage "ports": enslave the
    containerlab tenant ports, which only exist after container start.
    """
    tenancy = intent["tenants"]
    node = next(n for n in intent["nodes"] if n["name"] == leaf)
    vtep = node["loopback"].split("/")[0]
    mtu = tenancy["mtu"]
    port = tenancy["vxlan_udp_port"]
    lines = ["#!/bin/sh", "set -eu", f"# EVPN-VXLAN tenants on {leaf} ({stage}); VTEP {vtep}; rendered from intent"]

    def vxlan(vni: int, bridge: str) -> list[str]:
        return [
            f"ip link add vx{vni} type vxlan id {vni} local {vtep} dstport {port} nolearning",
            f"ip link set vx{vni} mtu {mtu} master {bridge} addrgenmode none",
            f"ip link set vx{vni} type bridge_slave neigh_suppress on learning off",
        ]

    for vrf in leaf_vrfs(intent, leaf):
        l3, seg = vrf["l3vni"], vrf["segment"]
        l2 = seg["l2vni"]
        if stage in ("devices", "all"):
            lines += [
                f"# {vrf['name']}: VRF table {vrf['table']}, L3VNI {l3}, L2VNI {l2} {seg['subnet']}",
                f"for dev in vx{l2} br{l2} vx{l3} br{l3} {vrf['name']}; do ip link del $dev 2>/dev/null || true; done",
                f"ip link add {vrf['name']} type vrf table {vrf['table']}",
                f"ip link set {vrf['name']} up",
                f"ip link add br{l3} type bridge",
                f"ip link set br{l3} master {vrf['name']} addrgenmode none",
                *vxlan(l3, f"br{l3}"),
                f"ip link set br{l3} mtu {mtu} up",
                f"ip link set vx{l3} up",
                f"ip link add br{l2} type bridge",
                f"ip link set br{l2} master {vrf['name']}",
                f"ip link set br{l2} address {tenancy['gateway_mac']}",
                *vxlan(l2, f"br{l2}"),
                f"ip link set br{l2} mtu {mtu} up",
                f"ip address replace {seg['gateway']} dev br{l2}",
                f"ip link set vx{l2} up",
            ]
        if stage in ("ports", "all"):
            for port_name in seg["ports"]:
                lines.append(f"ip link set {port_name} mtu {mtu} master br{l2} up")
            if seg["ports"]:
                lines.append(f"ip link set br{l2} mtu {mtu}")
    if stage == "ports":
        # Verify, do not repair: every L3VNI must carry the rendered RT. The
        # VRF BGP instances are rendered before the default instance (which
        # holds advertise-all-vni); in the other order FRR 10.2.1 auto-created
        # a VRF instance with router-id 0.0.0.0 and AS:VNI RTs on leaf2.
        for vrf in leaf_vrfs(intent, leaf):
            l3, rt = vrf["l3vni"], vrf["route_target"]
            lines.append(
                f"i=0; until vtysh -c 'show bgp l2vpn evpn vni {l3}' 2>/dev/null | grep -q '{rt}'; "
                f"do i=$((i+1)); [ $i -ge 60 ] && echo 'L3VNI {l3} lacks RT {rt}' >&2 && exit 1; sleep 1; done"
            )
    return "\n".join(lines) + "\n"


def endpoint_nodes(intent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """containerlab node definitions for tenant endpoints."""
    nodes: dict[str, dict[str, Any]] = {}
    if "tenants" not in intent:
        return nodes
    mtu = intent["tenants"]["mtu"]
    for vrf in intent["tenants"]["vrfs"]:
        for endpoint in vrf["endpoints"]:
            interface = endpoint_interface(intent, endpoint["name"])
            address = ipaddress.ip_interface(endpoint["address"])
            gateway = address.network.network_address + 1
            nodes[endpoint["name"]] = {
                "kind": "linux",
                "image": intent["images"]["tenant"],
                "cmd": "sleep infinity",
                "cap-add": ["NET_ADMIN", "NET_RAW"],
                "labels": {"goodput.tenant": vrf["name"]},
                "exec": [
                    f"ip link set {interface} mtu {mtu} up",
                    f"ip address replace {endpoint['address']} dev {interface}",
                    f"ip route replace default via {gateway} dev {interface}",
                ],
            }
    return nodes
