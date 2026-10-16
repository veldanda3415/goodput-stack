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
    assert len(intent["vm_hosts"]) == 2
    assert all({nic["rail"] for nic in host["nics"]} == {"A", "B"} for host in intent["hosts"])
    assert all(vm["memory_mib"] <= 1024 and len(vm["nics"]) == 1 for vm in intent["vm_hosts"])


def test_rejects_vm_host_over_one_gib() -> None:
    intent = raw_intent()
    intent["vm_hosts"][0]["memory_mib"] = 1025
    with pytest.raises(ValueError, match="memory_mib must be between 128 and 1024"):
        validate_semantics(intent)


def test_rejects_duplicate_vm_mac_addresses() -> None:
    intent = raw_intent()
    intent["vm_hosts"][1]["management_mac"] = intent["vm_hosts"][0]["management_mac"]
    with pytest.raises(ValueError, match="duplicate VM MAC address"):
        validate_semantics(intent)


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
    assert len(topology["topology"]["nodes"]) == 14
    assert topology["topology"]["nodes"]["spine1-tap"]["network-mode"] == "container:spine1"
    assert len(topology["topology"]["links"]) == 18
    assert topology["mgmt"]["ipv4-subnet"] == "10.253.0.0/24"
    assert all(node["privileged"] for node in topology["topology"]["nodes"].values())
    assert topology["topology"]["nodes"]["vmhost1"]["image"] == load_intent()["images"]["vmrunner"]
    assert "/dev/kvm:/dev/kvm" in topology["topology"]["nodes"]["vmhost1"]["binds"]
    network = yaml.safe_load((output / "vms/vmhost1/network-config").read_text(encoding="utf-8"))
    assert network["config"][1]["subnets"][0]["address"] == "10.210.0.18/30"
    assert network["config"][1]["subnets"][0]["routes"][0]["gateway"] == "10.210.0.17"
    assert all("set-name" not in nic for nic in network["config"])
    user_data = (output / "vms/vmhost1/user-data").read_text(encoding="utf-8")
    assert user_data.startswith("#cloud-config\n")
    assert "perftest=25.01.0+0.80-1" in user_data
    assert "netdev\n  - fabric" in user_data
    vm_config = yaml.safe_load(user_data)
    qos_script = vm_config["write_files"][0]["content"]
    assert "flower ip_tos 0x68/0xfc classid 1:2" in qos_script
    assert "tc qdisc add dev fabric root" in qos_script
    assert "__VM_SSH_PUBLIC_KEY__" in user_data


def test_renderer_configures_bgp_and_host_source_routing(tmp_path: Path) -> None:
    render(load_intent(), tmp_path)
    leaf_config = (tmp_path / "frr/leaf1/frr.conf").read_text(encoding="utf-8")
    spine_config = (tmp_path / "frr/spine1/frr.conf").read_text(encoding="utf-8")
    host_setup = (tmp_path / "hosts/host1-setup.sh").read_text(encoding="utf-8")
    assert "neighbor FABRIC remote-as 65000" in leaf_config
    assert "neighbor eth1 interface peer-group FABRIC" in leaf_config
    assert "neighbor eth2 interface peer-group FABRIC" in leaf_config
    assert "neighbor PEER_LEAF1 remote-as 65101" in spine_config
    assert "neighbor PEER_LEAF2 remote-as 65102" in spine_config
    assert "neighbor eth1 interface peer-group PEER_LEAF1" in spine_config
    assert "neighbor FABRIC route-map FABRIC-IN in" in leaf_config
    assert "maximum-paths 2" in leaf_config
    assert "ip address 10.210.0.1/30" in leaf_config
    assert "ip address 10.210.0.5/30" in leaf_config
    assert "ip rule add priority 101 from 10.210.0.2 table 101" in host_setup
    assert "rp_filter=2" in host_setup
