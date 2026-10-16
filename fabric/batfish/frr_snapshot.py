"""Build a Batfish snapshot of the *running* FRR render (unnumbered underlay).

Batfish has no standalone FRR format; it parses FRR inside the Cumulus
"concatenated" format: hostname, an /etc/network/interfaces section, a
ports.conf marker, then frr.conf starting with `frr version`. Unnumbered BGP
has no IPs to infer adjacency, so a `layer1_topology.json` (from intent
links) tells Batfish which interfaces face each other.
Docs: https://batfish.readthedocs.io/en/latest/formats.html ("Cumulus Linux")
and https://pybatfish.readthedocs.io/en/latest/formats.html#layer-1-topology.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fabric.intent.schema.validate import load_intent
from fabric.render.render import leaf_host_addresses
from fabric.render.shaping import fabric_ports

ROOT = Path(__file__).resolve().parents[2]
FRR_VERSION = "10.2.1"


def concatenated(intent: dict[str, Any], node: dict[str, Any], frr_conf: str) -> str:
    name = node["name"]
    lines = [
        name,
        "# This file describes the network interfaces available on your system",
        "# and how to activate them. For more information, see interfaces(5).",
        "auto lo",
        "iface lo inet loopback",
        f"    address {node['loopback']}",
        "",
    ]
    for port in fabric_ports(intent)[name]:
        lines += [f"auto {port}", f"iface {port}", ""]
    if node["role"] == "leaf":
        for port, address in leaf_host_addresses(intent, name).items():
            lines += [f"auto {port}", f"iface {port}", f"    address {address}", ""]
    lines += ["# ports.conf --", f"frr version {FRR_VERSION}"]
    return "\n".join(lines) + "\n" + frr_conf


def layer1(intent: dict[str, Any]) -> dict[str, Any]:
    edges = []
    for link in intent["links"]:
        if link["kind"] != "fabric":
            continue
        a = {"hostname": link["a"]["node"], "interfaceName": link["a"]["interface"]}
        b = {"hostname": link["b"]["node"], "interfaceName": link["b"]["interface"]}
        edges += [{"node1": a, "node2": b}, {"node1": b, "node2": a}]
    return {"edges": edges}


def build(intent: dict[str, Any], frr_dir: Path, output: Path) -> Path:
    configs = output / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    for node in intent["nodes"]:
        frr_conf = (frr_dir / node["name"] / "frr.conf").read_text(encoding="utf-8")
        (configs / f"{node['name']}.cfg").write_text(concatenated(intent, node, frr_conf), encoding="utf-8")
    (output / "layer1_topology.json").write_text(json.dumps(layer1(intent), indent=1) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frr", type=Path, default=ROOT / "fabric" / "build" / "frr")
    parser.add_argument("--output", type=Path, default=ROOT / "fabric" / "build" / "batfish" / "frr")
    args = parser.parse_args()
    print(f"Wrote Batfish FRR snapshot to {build(load_intent(), args.frr, args.output)}")


if __name__ == "__main__":
    main()
