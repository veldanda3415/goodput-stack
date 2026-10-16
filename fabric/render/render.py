from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fabric.intent.schema.validate import INTENT_PATH, load_intent
from fabric.render.qos import host_qos_script, sonic_config


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "frr"
LINUX_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "linux"
VM_RDMA_PACKAGES = [
    "rdma-core=56.1-1",
    "ibverbs-utils=56.1-1",
    "ibverbs-providers=56.1-1",
    "rdmacm-utils=56.1-1",
    "perftest=25.01.0+0.80-1",
    "iproute2=6.15.0-1",
    "iperf3=3.18-2+deb13u2",
    "tcpdump=4.99.5-2",
    "tshark=4.4.18-0+deb13u1",
    "sysstat=12.7.5-2",
    "procps=2:4.0.4-9",
    "iputils-ping=3:20240905-3",
    "traceroute=1:2.1.6-1",
    "openssh-server=1:10.0p1-7+deb13u4",
]


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
    for host in [*intent["hosts"], *intent.get("vm_hosts", [])]:
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
    linux_env = Environment(
        loader=FileSystemLoader(LINUX_TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    frr_template = env.get_template("frr.conf.j2")
    daemons_template = env.get_template("daemons.j2")
    hosts = {host["name"]: host for host in [*intent["hosts"], *intent.get("vm_hosts", [])]}
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
        sonic_dir = output / "sonic" / node["name"]
        sonic_dir.mkdir(parents=True, exist_ok=True)
        (sonic_dir / "config_db.qos.json").write_text(
            json.dumps(sonic_config(intent, node["name"]), indent=2) + "\n", encoding="utf-8"
        )
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
        if host_name in {vm["name"] for vm in intent.get("vm_hosts", [])}:
            continue
        setup_dir = output / "hosts"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (setup_dir / f"{host_name}-setup.sh").write_text(host_setup(host, intent["rdma"]), encoding="utf-8")
        (setup_dir / f"{host_name}-qos.sh").write_text(host_qos_script(linux_env, intent, host), encoding="utf-8")
        topology["topology"]["nodes"][host_name] = {
            "kind": "linux",
            "image": intent["images"]["host"],
            "privileged": True,
            "cmd": "sleep infinity",
            "binds": [
                f"./hosts/{host_name}-setup.sh:/usr/local/bin/host-setup.sh:ro",
                f"./hosts/{host_name}-qos.sh:/usr/local/bin/host-qos.sh:ro",
            ],
            "exec": ["sh /usr/local/bin/host-setup.sh", "sh /usr/local/bin/host-qos.sh"],
        }

    for vm_host in intent.get("vm_hosts", []):
        vm_dir = output / "vms" / vm_host["name"]
        vm_dir.mkdir(parents=True, exist_ok=True)
        nic = vm_host["nics"][0]
        config = "\n".join([
            f"VM_NAME={vm_host['name']}",
            f"VM_MEMORY_MIB={vm_host['memory_mib']}",
            f"VM_CPUS={vm_host['vcpus']}",
            f"VM_MANAGEMENT_MAC={vm_host['management_mac']}",
            f"VM_FABRIC_MAC={nic['mac']}",
            "",
        ])
        (vm_dir / "config").write_text(config, encoding="utf-8")
        (vm_dir / "meta-data").write_text(
            yaml.safe_dump({"instance-id": vm_host["name"], "local-hostname": vm_host["name"]}),
            encoding="utf-8",
        )
        user_data = {
            "hostname": vm_host["name"],
            "manage_etc_hosts": True,
            "apt": {"preserve_sources_list": True},
            "bootcmd": [[
                "sh", "-c",
                "rm -f /etc/apt/sources.list.d/*.sources; "
                "printf '%s\\n' 'deb [check-valid-until=no] "
                "http://snapshot.debian.org/archive/debian/20260918T000000Z trixie main' "
                "> /etc/apt/sources.list",
            ]],
            "package_update": True,
            "packages": VM_RDMA_PACKAGES,
            "ssh_pwauth": False,
            "users": [
                "default",
                {
                    "name": "fabric",
                    "shell": "/bin/bash",
                    "groups": ["sudo"],
                    "sudo": "ALL=(ALL) NOPASSWD:ALL",
                    "lock_passwd": True,
                    "ssh_authorized_keys": ["__VM_SSH_PUBLIC_KEY__"],
                },
            ],
            "runcmd": [
                ["modprobe", "rdma_rxe"],
                ["ip", "route", "replace", "10.210.0.0/16", "via", nic["gateway"], "dev", "fabric"],
                ["rdma", "link", "add", f"rxe_{vm_host['name']}_a", "type", "rxe", "netdev", "fabric"],
            ],
        }
        (vm_dir / "user-data").write_text(
            "#cloud-config\n" + yaml.safe_dump(user_data, sort_keys=False),
            encoding="utf-8",
        )
        network_config = {
            "version": 1,
            "config": [
                {
                    "type": "physical",
                    "name": "management",
                    "mac_address": vm_host["management_mac"],
                    "subnets": [{"type": "dhcp"}],
                },
                {
                    "type": "physical",
                    "name": "fabric",
                    "mac_address": nic["mac"],
                    "subnets": [{
                        "type": "static",
                        "address": nic["address"],
                        "routes": [{
                            "network": "10.210.0.0",
                            "netmask": "255.255.0.0",
                            "gateway": nic["gateway"],
                        }],
                    }],
                },
            ],
        }
        (vm_dir / "network-config").write_text(
            yaml.safe_dump(network_config, sort_keys=False),
            encoding="utf-8",
        )
        topology["topology"]["nodes"][vm_host["name"]] = {
            "kind": "linux",
            "image": intent["images"]["vmrunner"],
            "privileged": True,
            "cmd": "/usr/local/sbin/vmhost-start",
            "binds": [
                f"./vms/{vm_host['name']}:/run/vm:ro",
                "/dev/kvm:/dev/kvm",
                "/dev/net/tun:/dev/net/tun",
            ],
        }

    for router in intent["capture_taps"]:
        topology["topology"]["nodes"][f"{router}-tap"] = {
            "kind": "linux",
            "image": intent["images"]["host"],
            "privileged": True,
            "network-mode": f"container:{router}",
            "cmd": "sleep infinity",
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
            for host in [*intent["hosts"], *intent.get("vm_hosts", [])]
            for nic in host["nics"]
            if nic["leaf"] == node_name
        )
    return sorted(prefixes)


def rdma_device(host_name: str, rail: str) -> str:
    """Global rxe device name; shared RDMA netns mode makes names host-wide."""
    return f"rxe_{host_name}_{rail.lower()}"


def host_setup(host: dict[str, Any], rdma: dict[str, Any]) -> str:
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
    if rdma["enabled"]:
        for nic in host["nics"]:
            device = rdma_device(host["name"], nic["rail"])
            lines.append(
                f"rdma link show {device}/1 >/dev/null 2>&1 || "
                f"rdma link add {device} type {rdma['provider']} netdev {nic['interface']}"
            )
        # The container's /dev was populated at creation, before these devices
        # existed; add the missing uverbs character devices from sysfs.
        lines.append(
            "for v in /sys/class/infiniband_verbs/uverbs*; do n=${v##*/}; "
            "[ -e /dev/infiniband/$n ] || mknod /dev/infiniband/$n c $(tr : ' ' < $v/dev); done"
        )
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
