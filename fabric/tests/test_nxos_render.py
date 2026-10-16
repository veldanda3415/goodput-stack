"""NX-OS renderer: golden file + structural checks (OFFLINE; no Batfish needed)."""
from __future__ import annotations

import ipaddress
from pathlib import Path

from fabric.intent.schema.validate import load_intent
from fabric.render.nxos import p2p_addresses, render_node

GOLDEN = Path(__file__).with_name("golden")


def node(intent: dict, name: str) -> dict:
    return next(n for n in intent["nodes"] if n["name"] == name)


def test_leaf1_numbered_render_matches_golden() -> None:
    intent = load_intent()
    rendered = render_node(intent, node(intent, "leaf1"), "numbered")
    assert rendered == (GOLDEN / "leaf1.nxos.numbered.cfg").read_text(encoding="utf-8")


def test_spine1_unnumbered_render_matches_golden() -> None:
    intent = load_intent()
    rendered = render_node(intent, node(intent, "spine1"), "unnumbered")
    assert rendered == (GOLDEN / "spine1.nxos.unnumbered.cfg").read_text(encoding="utf-8")


def test_p2p_pool_gives_each_fabric_link_a_distinct_31_inside_the_pool() -> None:
    intent = load_intent()
    pool = ipaddress.ip_network(intent["address_plan"]["fabric_p2p"])
    addresses = p2p_addresses(intent)
    fabric_links = [link for link in intent["links"] if link["kind"] == "fabric"]
    assert len(addresses) == 2 * len(fabric_links)
    nets = {ipaddress.ip_interface(local).network for local, _ in addresses.values()}
    assert len(nets) == len(fabric_links) and all(net.subnet_of(pool) and net.prefixlen == 31 for net in nets)
    for (name, interface), (local, peer) in addresses.items():
        assert ipaddress.ip_address(peer) in ipaddress.ip_interface(local).network


def test_every_switch_has_bgp_bfd_and_ecmp_from_intent() -> None:
    intent = load_intent()
    for router in intent["nodes"]:
        config = render_node(intent, router, "numbered")
        assert "feature bgp" in config and "feature bfd" in config
        assert f"router bgp {router['asn']}" in config
        assert f"maximum-paths {intent['ecmp_width']}" in config
        neighbors = config.count("    remote-as ")
        assert neighbors == (4 if router["role"] == "spine" else 2)
        assert config.count("    bfd\n") == neighbors
