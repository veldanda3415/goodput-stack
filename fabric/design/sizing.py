"""CALCULATED switch, link and transceiver counts for an AI cluster's networks.

Topologies for the scale-out backend: rail-optimized leaf-spine (one leaf group per
rail; DGX SuperPOD, sources.md S9), plain leaf-spine (one leaf per rack, every NIC of
a node on that leaf), and rail-only (no spine; cross-rail traffic forwarded over
NVLink, Wang et al., S11). Nothing here is measured. Derivations: fabric/DESIGN.md §3.

    python -m fabric.design.sizing [--config fabric/design/inputs.yaml] [--gpus 256 2048]
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from fabric.design.collectives import table

DEFAULT_CONFIG = Path(__file__).with_name("inputs.yaml")


def leaf_ports(radix: int, oversub: float) -> tuple[int, int]:
    """Split a leaf's ports into (down, up) for an oversubscription down:up = oversub:1."""
    down = math.floor(radix * oversub / (1 + oversub))
    return down, radix - down


def two_tier_max(radix: int, oversub: float = 1.0) -> int:
    """Each spine port reaches a different leaf, so at most `radix` leaves: k * down.
    Non-blocking: k * k/2."""
    return radix * leaf_ports(radix, oversub)[0]


def three_tier_max(radix: int) -> int:
    """Non-blocking three-tier fat tree: k pods * (k/2 leaves * k/2 hosts) = k^3/4."""
    return radix ** 3 // 4


def pair_fraction_within(group_sizes: list[int]) -> float:
    """Fraction of endpoint pairs whose two endpoints share a group."""
    total = sum(group_sizes)
    if total < 2:
        return 1.0
    same = sum(g * (g - 1) for g in group_sizes)
    return same / (total * (total - 1))


def spread(n: int, bins: int) -> list[int]:
    base, extra = divmod(n, bins)
    return [base + (1 if i < extra else 0) for i in range(bins)]


@dataclass
class Fabric:
    topology: str
    tiers: int
    leaves: int
    spines: int
    super_spines: int
    nic_links: int
    switch_links: int
    copper_links: int
    optical_ends: int
    one_hop_same_rail: float
    max_hops: str
    bisection_tbps: float
    notes: str = ""


def clos(groups: list[int], radix: int, oversub: float, min_spines: int = 1) -> dict:
    """Leaf-spine over endpoint groups that each need their own leaves (rails, racks).
    Leaves of a group are built uniformly; uplinks = ceil(max down used / oversub),
    rounded up so each leaf has the same number of links to every spine."""
    down, _ = leaf_ports(radix, oversub)
    leaves_per_group = [math.ceil(g / down) for g in groups]
    leaf_down = [d for g, n in zip(groups, leaves_per_group) for d in spread(g, n)]
    n_leaves = len(leaf_down)
    if n_leaves > radix:
        return {}
    up = math.ceil(max(leaf_down) / oversub)
    spines = max(min_spines, math.ceil(n_leaves * up / radix))
    while True:
        per_spine = math.ceil(up / spines)
        if n_leaves * per_spine <= radix:
            break
        spines += 1
    return {"leaves": n_leaves, "spines": spines, "uplinks": spines * per_spine,
            "leaf_down": leaf_down, "leaves_per_group": leaves_per_group}


def three_tier(n_endpoints: int, radix: int) -> dict:
    half = radix // 2
    pods = math.ceil(n_endpoints / (half * half))
    leaves = math.ceil(n_endpoints / half)
    spines = pods * half
    return {"leaves": leaves, "spines": spines, "super_spines": math.ceil(pods * half * half / radix),
            "leaf_spine_links": leaves * half, "spine_super_links": pods * half * half}


def backend(gpus: int, gpus_per_node: int, nics_per_node: int, port_gbps: int, radix: int,
            oversub: float, nodes_per_rack: int) -> list[Fabric]:
    nodes = gpus // gpus_per_node
    nics = nodes * nics_per_node
    rails = nics_per_node
    half_bisection = nics / 2 * port_gbps / oversub / 1000
    out: list[Fabric] = []

    # Rail-optimized: NIC r of every node goes to rail r's leaves (S9).
    c = clos([nodes] * rails, radix, oversub)
    if c:
        nodes_per_leaf = c["leaf_down"][: c["leaves_per_group"][0]]
        copper = nics if max(c["leaf_down"]) <= nodes_per_rack else 0
        sw = c["leaves"] * c["uplinks"]
        out.append(Fabric("rail-optimized leaf-spine", 2, c["leaves"], c["spines"], 0, nics, sw,
                          copper, 2 * (nics - copper + sw), pair_fraction_within(nodes_per_leaf),
                          "3", half_bisection))
    else:
        t = three_tier(nics, radix)
        sw = t["leaf_spine_links"] + t["spine_super_links"]
        out.append(Fabric("rail-optimized leaf-spine", 3, t["leaves"], t["spines"], t["super_spines"],
                          nics, sw, 0, 2 * (nics + sw),
                          pair_fraction_within(spread(nodes, math.ceil(nodes / (radix // 2)))),
                          "5", half_bisection, "beyond the 2-tier ceiling"))

    # Plain leaf-spine: one leaf per rack, all NICs of the rack's nodes on it.
    racks = math.ceil(nodes / nodes_per_rack)
    rack_nics = [n * nics_per_node for n in spread(nodes, racks)]
    c = clos(rack_nics, radix, oversub)
    if c:
        sw = c["leaves"] * c["uplinks"]
        rack_nodes = spread(nodes, racks)
        out.append(Fabric("plain leaf-spine (leaf per rack)", 2, c["leaves"], c["spines"], 0, nics,
                          sw, nics, 2 * sw, pair_fraction_within(rack_nodes), "3", half_bisection,
                          "NIC links in-rack, copper-capable (≤ 3 m, S19)"))
    else:
        t = three_tier(nics, radix)
        sw = t["leaf_spine_links"] + t["spine_super_links"]
        out.append(Fabric("plain leaf-spine (leaf per rack)", 3, t["leaves"], t["spines"],
                          t["super_spines"], nics, sw, nics, 2 * sw,
                          pair_fraction_within(spread(nodes, racks)), "5", half_bisection,
                          "beyond the 2-tier ceiling"))

    # Rail-only: no spine. A rail fits one switch up to `radix` nodes; beyond, each rail is
    # its own leaf-spine. Cross-rail traffic goes over NVLink first (S11).
    if nodes <= radix:
        leaves, spines, sw = rails, 0, 0
        hops = "1 (cross-rail: NVLink + 1)"
        one_hop = 1.0
    else:
        c = clos([nodes], radix, oversub)
        if not c:
            raise ValueError("rail-only rail exceeds a 2-tier rail Clos")
        leaves, spines = c["leaves"] * rails, c["spines"] * rails
        sw = c["leaves"] * c["uplinks"] * rails
        hops = "3 (cross-rail: NVLink + 3)"
        one_hop = pair_fraction_within(c["leaf_down"])
    out.append(Fabric("rail-only (no spine)", 1 if spines == 0 else 2, leaves, spines, 0, nics, sw,
                      0, 2 * (nics + sw), one_hop, hops, 0.0,
                      f"no network path between rails; per-rail bisection "
                      f"{nodes / 2 * port_gbps / oversub / 1000:,.1f} Tb/s"))
    return out


def frontend(nodes: int, fe: dict) -> dict:
    ports = nodes * fe["ports_per_node"]
    c = clos([ports], fe["radix"], fe["oversubscription"], fe.get("min_spines", 1))
    return {"ports": ports, "leaves": c["leaves"], "spines": c["spines"],
            "uplinks": c["leaves"] * c["uplinks"]}


def oob(nodes: int, switches: int, o: dict) -> dict:
    ports = nodes * o["ports_per_node"] + switches  # one management port per switch (assumed)
    return {"ports": ports, "switches": math.ceil(ports / o["switch_ports"])}


# ---- Markdown -------------------------------------------------------------------------------


def backend_md(cfg: dict, gpu_counts: list[int]) -> str:
    hw, s = cfg["hardware"], cfg["sizing"]
    sw = s["backend_switch"]
    parts = []
    for g in gpu_counts:
        rows = []
        for f in backend(g, hw["gpus_per_node"], hw["nics_per_node"], sw["port_gbps"], sw["radix"],
                         s["oversubscription"], s["nodes_per_rack"]):
            rows.append([f.topology, str(f.tiers), f"{f.leaves:,}", f"{f.spines:,}",
                         f"{f.super_spines:,}", f"{f.nic_links:,}", f"{f.switch_links:,}",
                         f"{f.copper_links:,}", f"{f.optical_ends:,}", f"{f.one_hop_same_rail:.0%}",
                         f.max_hops, f"{f.bisection_tbps:,.1f}" if f.bisection_tbps else "n/a",
                         f.notes])
        nodes = g // hw["gpus_per_node"]
        parts.append(
            f"**Backend, {g:,} GPUs ({nodes} nodes × {hw['nics_per_node']} × "
            f"{sw['port_gbps']}G NICs), {sw['name']}, oversubscription "
            f"{s['oversubscription']:g}:1** — CALCULATED\n\n" + table(
                ["Topology", "Tiers", "Leaves", "Spines", "Super-spines", "NIC–leaf links",
                 "Switch–switch links", "Copper-capable links", "Optical transceivers (both ends)",
                 "Same-rail GPU pairs at 1 switch hop", "Max switch hops", "Bisection (Tb/s)",
                 "Notes"], rows))
    return "\n\n".join(parts)


def ceiling_md(cfg: dict) -> str:
    gpn = cfg["hardware"]["nics_per_node"]
    rows = []
    for sw in cfg["sizing"]["ceiling_switches"]:
        k = sw["radix"]
        two, three = two_tier_max(k), three_tier_max(k)
        rows.append([sw["name"], str(k), f"{sw['port_gbps']}G", f"{two:,}", f"{two // gpn * gpn:,}",
                     f"{three:,}"])
    return ("**Where two tiers stop (non-blocking; one NIC per GPU)** — CALCULATED\n\n" + table(
        ["Switch configuration", "Radix k", "Port speed", "2-tier max NICs = k²/2",
         f"2-tier max GPUs ({gpn} NICs/node)", "3-tier max NICs = k³/4"], rows))


def other_networks_md(cfg: dict, gpu_counts: list[int]) -> str:
    hw, s = cfg["hardware"], cfg["sizing"]
    sw = s["backend_switch"]
    rows = []
    for g in gpu_counts:
        nodes = g // hw["gpus_per_node"]
        be = backend(g, hw["gpus_per_node"], hw["nics_per_node"], sw["port_gbps"], sw["radix"],
                     s["oversubscription"], s["nodes_per_rack"])[0]
        fe = frontend(nodes, s["frontend"])
        mgmt = oob(nodes, be.leaves + be.spines + be.super_spines + fe["leaves"] + fe["spines"],
                   s["oob"])
        f = s["frontend"]
        rows.append([f"{g:,}", str(nodes),
                     f"{fe['ports']} × {f['port_gbps']}G; {fe['leaves']} leaves, {fe['spines']} "
                     f"spines ({f['oversubscription']:g}:1)",
                     f"{nodes * s['storage_gbytes_per_node']:,} GB/s "
                     f"({nodes * s['storage_gbytes_per_node'] * 8 / 1000:,.2f} Tb/s) aggregate",
                     f"{mgmt['ports']} × 1G ports; {mgmt['switches']} × {s['oob']['switch_ports']}-port",
                     f"{nodes * hw['node_power_kw']:,.1f}"])
    return ("**Front-end, storage and out-of-band networks** — CALCULATED\n\n" + table(
        ["GPUs", "Nodes", "Front-end (in-band)", "Storage demand at S10's ≥ 40 GB/s/node",
         "OOB management", "Node power, max (kW)"], rows))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--gpus", type=int, nargs="+")
    a = p.parse_args(argv)
    cfg = yaml.safe_load(a.config.read_text())
    counts = a.gpus or cfg["sizing"]["gpu_counts"]
    print("\n\n".join([backend_md(cfg, counts), ceiling_md(cfg), other_networks_md(cfg, counts)]))


if __name__ == "__main__":
    main()
