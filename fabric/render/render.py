from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fabric.intent.schema.validate import INTENT_PATH, load_intent


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "frr"


def router_peer_groups(intent: dict[str, Any], name: str) -> list[dict[str, Any]]:
    nodes = {node["name"]: node for node in intent["nodes"]}
    local = nodes[name]
    peer_links: list[tuple[str, str, int]] = []
    for link in intent["links"]:
        if link["kind"] != "fabric":
            continue
        endpoints = (link["a"], link["b"])
        local_endpoint = next((endpoint for endpoint in endpoints if endpoint["node"] == name), None)
        if local_endpoint is None:
            continue
        peer_endpoint = next(endpoint for endpoint in endpoints if endpoint["node"] != name)
        peer_links.append((
            local_endpoint["interface"],
            peer_endpoint["node"],
            nodes[peer_endpoint["node"]]["asn"],
        ))
    peer_links.sort()
    if local["role"] == "leaf":
        return [{
            "name": "FABRIC",
            "asn": intent["bgp"]["spine_asn"],
            "interfaces": [interface for interface, _, _ in peer_links],
        }]
    return [
        {
            "name": f"PEER_{peer_name.upper()}",
            "asn": remote_asn,
            "interfaces": [interface],
        }
        for interface, peer_name, remote_asn in peer_links
    ]


def leaf_host_addresses(intent: dict[str, Any], name: str) -> dict[str, str]:
    assigned: dict[str, str] = {}
    for host in intent["hosts"]:
        for nic in host["nics"]:
            if nic["leaf"] == name:
                leaf_interface = next(
                    endpoint["interface"]
                    for link in intent["links"]
                    if link["kind"] == "host"
                    for endpoint in (link["a"], link["b"])
                    if endpoint["node"] == name
                    and any(
                        peer["node"] == host["name"] and peer["interface"] == nic["interface"]
                        for peer in (link["a"], link["b"])
                    )
                )
                leaf_address = str(ipaddress.ip_network(nic["subnet"]).network_address + 1)
                assigned[leaf_interface] = f"{leaf_address}/{ipaddress.ip_network(nic['subnet']).prefixlen}"
    return assigned


def render(intent: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    frr_template = env.get_template("frr.conf.j2")
    daemons_template = env.get_template("daemons.j2")
    hosts = {host["name"]: host for host in intent["hosts"]}
    topology: dict[str, Any] = {
        "name": intent["name"],
        "mgmt": {
            "network": f"{intent['name']}-mgmt",
            "ipv4-subnet": intent["address_plan"]["management"],
        },
        "topology": {"nodes": {}, "links": []},
    }

    for node in intent["nodes"]:
        node_dir = output / "frr" / node["name"]
        node_dir.mkdir(parents=True, exist_ok=True)
        host_addresses = leaf_host_addresses(intent, node["name"]) if node["role"] == "leaf" else {}
        (node_dir / "frr.conf").write_text(
            frr_template.render(
                intent=intent,
                node=node,
                peer_groups=router_peer_groups(intent, node["name"]),
                host_addresses=host_addresses,
                advertised_prefixes=advertised_prefixes(intent, node["name"]),
            ),
            encoding="utf-8",
        )
        (node_dir / "daemons").write_text(daemons_template.render(), encoding="utf-8")
        topology["topology"]["nodes"][node["name"]] = {
            "kind": "linux",
            "image": intent["images"]["frr"],
            "privileged": True,
            "binds": [
                f"./frr/{node['name']}/frr.conf:/etc/frr/frr.conf:ro",
                f"./frr/{node['name']}/daemons:/etc/frr/daemons:ro",
            ],
            "exec": [
                "sysctl -w net.ipv4.conf.all.rp_filter=0",
                "sysctl -w net.ipv4.conf.default.rp_filter=0",
                "sysctl -w net.ipv4.ip_forward=1",
                "sysctl -w net.ipv6.conf.all.forwarding=1",
            ],
        }

    for host_name, host in hosts.items():
        setup_dir = output / "hosts"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (setup_dir / f"{host_name}-setup.sh").write_text(host_setup(host), encoding="utf-8")
        topology["topology"]["nodes"][host_name] = {
            "kind": "linux",
            "image": intent["images"]["host"],
            "privileged": True,
            "cmd": "sleep infinity",
            "binds": [f"./hosts/{host_name}-setup.sh:/usr/local/bin/host-setup.sh:ro"],
            "exec": ["sh /usr/local/bin/host-setup.sh"],
        }

    for link in intent["links"]:
        topology["topology"]["links"].append({
            "endpoints": [
                f"{link['a']['node']}:{link['a']['interface']}",
                f"{link['b']['node']}:{link['b']['interface']}",
            ]
        })
    (output / "topology.clab.yml").write_text(
        yaml.safe_dump(topology, sort_keys=False), encoding="utf-8"
    )
    (output / "render-manifest.json").write_text(
        json.dumps(
            {
                "intent": str(INTENT_PATH.relative_to(ROOT)),
                "images": intent["images"],
                "rendered_nodes": sorted(topology["topology"]["nodes"]),
                "links": len(topology["topology"]["links"]),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def advertised_prefixes(intent: dict[str, Any], node_name: str) -> list[str]:
    node = next(router for router in intent["nodes"] if router["name"] == node_name)
    prefixes = [node["loopback"]]
    if node["role"] == "leaf":
        prefixes.extend(
            nic["subnet"]
            for host in intent["hosts"]
            for nic in host["nics"]
            if nic["leaf"] == node_name
        )
    return sorted(prefixes)


def host_setup(host: dict[str, Any]) -> str:
    lines = [
        "#!/bin/sh",
        "set -eu",
        "sysctl -w net.ipv4.conf.all.rp_filter=2 >/dev/null",
        "sysctl -w net.ipv4.conf.default.rp_filter=2 >/dev/null",
    ]
    for table, nic in enumerate(host["nics"], start=101):
        address = nic["address"]
        lines.extend([
            f"ip link set dev {nic['interface']} up",
            f"ip address replace {address} dev {nic['interface']}",
            f"ip route replace {nic['subnet']} dev {nic['interface']} src {address.split('/')[0]} table {table}",
            f"ip route replace default via {nic['gateway']} dev {nic['interface']} table {table}",
            f"ip rule add priority {table} from {address.split('/')[0]} table {table}",
        ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate fabric intent and render its FRR lab")
    parser.add_argument("--intent", type=Path, default=INTENT_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "fabric" / "build")
    parser.add_argument("--example", action="store_true", help="write the committed example render")
    args = parser.parse_args()
    output = ROOT / "fabric" / "build" / "example" if args.example else args.output
    intent = load_intent(args.intent)
    render(intent, output)
    print(f"Rendered {intent['name']} to {output}")


if __name__ == "__main__":
    main()
