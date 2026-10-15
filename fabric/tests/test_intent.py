from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from fabric.intent.schema.validate import INTENT_PATH, load_intent, validate_semantics
from fabric.render.render import render


def raw_intent() -> dict:
    with INTENT_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_intent_is_valid_and_has_rail_optimized_shape() -> None:
    intent = load_intent()
    assert len([node for node in intent["nodes"] if node["role"] == "spine"]) == 2
    assert len([node for node in intent["nodes"] if node["role"] == "leaf"]) == 4
    assert len(intent["hosts"]) == 4
    assert all({nic["rail"] for nic in host["nics"]} == {"A", "B"} for host in intent["hosts"])


def test_rejects_duplicate_leaf_asn() -> None:
    intent = raw_intent()
    intent["nodes"][3]["asn"] = intent["nodes"][2]["asn"]
    with pytest.raises(ValueError, match="leaf ASNs must be unique"):
        validate_semantics(intent)


def test_rejects_missing_link_endpoint() -> None:
    intent = raw_intent()
    intent["links"][0]["b"]["node"] = "missing-leaf"
    with pytest.raises(ValueError, match="missing endpoint missing-leaf"):
        validate_semantics(intent)


def test_rejects_overlapping_excluded_range() -> None:
    intent = raw_intent()
    intent["address_plan"]["hosts"] = "10.42.0.0/16"
    with pytest.raises(ValueError, match="overlaps excluded network"):
        validate_semantics(intent)


def test_rejects_host_missing_rail_nic() -> None:
    intent = raw_intent()
    intent["hosts"][0]["nics"].pop()
    with pytest.raises(ValueError, match="exactly one NIC per rail"):
        validate_semantics(intent)


def test_rejects_host_subnet_outside_declared_pool() -> None:
    intent = raw_intent()
    intent["hosts"][0]["nics"][0]["subnet"] = "10.211.0.0/30"
    intent["hosts"][0]["nics"][0]["address"] = "10.211.0.2/30"
    intent["hosts"][0]["nics"][0]["gateway"] = "10.211.0.1"
    with pytest.raises(ValueError, match="outside address_plan.hosts"):
        validate_semantics(intent)


def test_rejects_unpinned_container_image() -> None:
    intent = raw_intent()
    intent["images"]["host"] = "docker.io/nicolaka/netshoot:latest"
    with pytest.raises(ValueError, match="version tag and sha256 digest"):
        validate_semantics(intent)


def test_renderer_is_byte_deterministic(tmp_path: Path) -> None:
    intent = load_intent()
    output = tmp_path / "render"
    render(intent, output)
    first = {
        path.relative_to(output): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    render(intent, output)
    second = {
        path.relative_to(output): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    assert first == second
    topology = yaml.safe_load((output / "topology.clab.yml").read_text(encoding="utf-8"))
    assert len(topology["topology"]["nodes"]) == 10
    assert len(topology["topology"]["links"]) == 16
    assert topology["mgmt"]["ipv4-subnet"] == "10.253.0.0/24"
    assert all(node["privileged"] for node in topology["topology"]["nodes"].values())


def test_renderer_configures_bgp_and_host_source_routing(tmp_path: Path) -> None:
    render(load_intent(), tmp_path)
    leaf_config = (tmp_path / "frr/leaf1/frr.conf").read_text(encoding="utf-8")
    host_setup = (tmp_path / "hosts/host1-setup.sh").read_text(encoding="utf-8")
    assert "neighbor eth1 interface peer-group FABRIC" in leaf_config
    assert "neighbor eth2 interface peer-group FABRIC" in leaf_config
    assert "maximum-paths 2" in leaf_config
    assert "ip address 10.210.0.1/30" in leaf_config
    assert "ip address 10.210.0.5/30" in leaf_config
    assert "ip rule add priority 101 from 10.210.0.2 table 101" in host_setup
    assert "rp_filter=2" in host_setup
