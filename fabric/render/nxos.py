"""Second renderer: Cisco NX-OS configs from the same fabric intent.

OFFLINE-VALIDATED only (Batfish); never deployed on NX-OS 9000v or hardware.
Sources:
- Cisco Nexus 9000 Series NX-OS Unicast Routing Configuration Guide, Release
  10.2(x), "Configuring Advanced BGP": "Load sharing and multipath"
  (maximum-paths), "BFD" (BFD for eBGP peers), and "Configure BGP Interface
  Peering via IPv6 Link-Local for IPv4 and IPv6 Address Families"
  (`neighbor Ethernet1/1 remote-as`, `ipv6 address use-link-local-only`,
  `ipv6 link-local use-bia`, `ip forward` when the interface has no IPv4):
  https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/102x/configuration/Unicast-routing/cisco-nexus-9000-series-nx-os-unicast-routing-configuration-guide-release-102x/m-n9k-configuring-advanced-bgp-102x.html
- Cisco tech note 221944 "Configure and Verify BFD on Nexus 9000 Switches"
  (`feature bfd`, `bfd interval <ms> min_rx <ms> multiplier <n>`, disable ICMP
  redirects with `no ip redirects` on BFD interfaces):
  https://www.cisco.com/c/en/us/support/docs/switches/nexus-9000-series-switches/221944-configure-and-verify-bfd-on-nexus-9000-s.html

Underlay variants from one intent:
  numbered    /31 per fabric link from address_plan.fabric_p2p (a = .even)
  unnumbered  `neighbor EthernetX/Y` over IPv6 link-local, as the FRR lab runs

Usage: python -m fabric.render.nxos [--variant numbered|unnumbered] [--output DIR]
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
from typing import Any

from fabric.intent.schema.validate import INTENT_PATH, load_intent
from fabric.render.render import advertised_prefixes, leaf_host_addresses

ROOT = Path(__file__).resolve().parents[2]
NXOS_MAX_MTU = 9216  # Nexus 9000 maximum L3 interface MTU


def nx_interface(interface: str) -> str:
    """Lab `ethN` -> front-panel `Ethernet1/N` (placeholder port map)."""
    return f"Ethernet1/{int(interface.removeprefix('eth'))}"


def p2p_addresses(intent: dict[str, Any]) -> dict[tuple[str, str], tuple[str, str]]:
    """(node, interface) -> (local /31 address, peer address) per fabric link."""
    pool = ipaddress.ip_network(intent["address_plan"]["fabric_p2p"])
    subnets = pool.subnets(new_prefix=31)
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for link in (link for link in intent["links"] if link["kind"] == "fabric"):
        net = next(subnets)
        a, b = net[0], net[1]
        out[(link["a"]["node"], link["a"]["interface"])] = (f"{a}/31", str(b))
        out[(link["b"]["node"], link["b"]["interface"])] = (f"{b}/31", str(a))
    return out


def fabric_neighbors(intent: dict[str, Any], name: str) -> list[dict[str, Any]]:
    nodes = {node["name"]: node for node in intent["nodes"]}
    neighbors = []
    for link in intent["links"]:
        if link["kind"] != "fabric":
            continue
        ends = (link["a"], link["b"])
        local = next((ep for ep in ends if ep["node"] == name), None)
        if local is None:
            continue
        peer = next(ep for ep in ends if ep["node"] != name)
        neighbors.append({
            "interface": local["interface"],
            "peer": peer["node"],
            "peer_interface": peer["interface"],
            "peer_asn": nodes[peer["node"]]["asn"],
            "link": link["name"],
        })
    return sorted(neighbors, key=lambda item: int(item["interface"].removeprefix("eth")))


def host_ports(intent: dict[str, Any], name: str) -> list[dict[str, str]]:
    hosts = [*intent["hosts"], *intent.get("vm_hosts", [])]
    out = []
    addresses = leaf_host_addresses(intent, name)
    for interface, address in sorted(addresses.items(), key=lambda kv: int(kv[0].removeprefix("eth"))):
        owner = next(
            (host["name"], nic["rail"])
            for host in hosts for nic in host["nics"]
            if nic["leaf"] == name and ipaddress.ip_interface(address).network == ipaddress.ip_network(nic["subnet"])
        )
        out.append({"interface": interface, "address": address, "host": owner[0], "rail": owner[1]})
    return out


def render_node(intent: dict[str, Any], node: dict[str, Any], variant: str) -> str:
    name = node["name"]
    mtu = min(intent.get("fabric_mtu", 1500), NXOS_MAX_MTU)
    bfd = intent["bfd"]
    bgp = intent["bgp"]
    p2p = p2p_addresses(intent) if variant == "numbered" else {}
    neighbors = fabric_neighbors(intent, name)
    lines = [
        "!RANCID-CONTENT-TYPE: cisco-nx",
        f"! {name}: rendered from fabric/intent/fabric.yaml ({variant} underlay); OFFLINE-VALIDATED only",
        f"hostname {name}",
        "feature bgp",
    ]
    if bfd["enabled"]:
        lines.append("feature bfd")
    lines += [
        "!",
        "interface loopback0",
        "  description router-id",
        f"  ip address {node['loopback']}",
        "!",
    ]
    for neighbor in neighbors:
        lines += [
            f"interface {nx_interface(neighbor['interface'])}",
            f"  description fabric {neighbor['peer']} {nx_interface(neighbor['peer_interface'])} ({neighbor['link']})",
            "  no switchport",
            f"  mtu {mtu}",
        ]
        if bfd["enabled"]:
            lines.append("  no ip redirects")
        if variant == "numbered":
            lines.append(f"  ip address {p2p[(name, neighbor['interface'])][0]}")
        else:
            lines += [
                "  ipv6 address use-link-local-only",
                "  ipv6 link-local use-bia",
                "  ip forward",
            ]
        if bfd["enabled"]:
            lines.append(
                f"  bfd interval {bfd['transmit_ms']} min_rx {bfd['receive_ms']} multiplier {bfd['detect_multiplier']}"
            )
        lines += ["  no shutdown", "!"]
    for port in host_ports(intent, name) if node["role"] == "leaf" else []:
        lines += [
            f"interface {nx_interface(port['interface'])}",
            f"  description rail {port['rail']} {port['host']}",
            "  no switchport",
            f"  mtu {mtu}",
            f"  ip address {port['address']}",
            "  no shutdown",
            "!",
        ]
    lines += [
        f"router bgp {node['asn']}",
        f"  router-id {node['loopback'].split('/')[0]}",
        "  log-neighbor-changes",
        "  address-family ipv4 unicast",
    ]
    lines += [f"    network {prefix}" for prefix in advertised_prefixes(intent, name)]
    if intent.get("ecmp_width"):
        lines.append(f"    maximum-paths {intent['ecmp_width']}")
    for neighbor in neighbors:
        target = p2p[(name, neighbor["interface"])][1] if variant == "numbered" else nx_interface(neighbor["interface"])
        lines += [
            f"  neighbor {target}",
            f"    remote-as {neighbor['peer_asn']}",
            f"    description {neighbor['peer']}",
            f"    timers {bgp['keepalive_seconds']} {bgp['hold_seconds']}",
        ]
        if bfd["enabled"]:
            lines.append("    bfd")
        lines += ["    address-family ipv4 unicast"]
    return "\n".join(lines) + "\n"


def render_nxos(intent: dict[str, Any], output: Path, variant: str) -> list[Path]:
    configs = output / variant / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    written = []
    for node in intent["nodes"]:
        path = configs / f"{node['name']}.cfg"
        path.write_text(render_node(intent, node, variant), encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--intent", type=Path, default=INTENT_PATH)
    parser.add_argument("--variant", choices=["numbered", "unnumbered", "both"], default="both")
    parser.add_argument("--output", type=Path, default=ROOT / "fabric" / "build" / "nxos")
    args = parser.parse_args()
    intent = load_intent(args.intent)
    for variant in (["numbered", "unnumbered"] if args.variant == "both" else [args.variant]):
        paths = render_nxos(intent, args.output, variant)
        print(f"Rendered {len(paths)} NX-OS configs ({variant}) to {args.output / variant / 'configs'}")


if __name__ == "__main__":
    main()
