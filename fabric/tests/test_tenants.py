"""EVPN-VXLAN tenant intent/render checks and running-lab reachability/isolation."""
from __future__ import annotations

import copy
import ipaddress

import pytest
import yaml

from fabric.intent.schema.validate import INTENT_PATH, load_intent, validate_semantics
from fabric.render.tenants import leaf_tenant_script, leaf_vrfs
from fabric.tests.lab import node_result


def raw_intent() -> dict:
    with INTENT_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def endpoints(intent: dict) -> dict[str, dict]:
    return {
        ep["name"]: {**ep, "vrf": vrf["name"], "ip": ep["address"].split("/")[0]}
        for vrf in intent["tenants"]["vrfs"] for ep in vrf["endpoints"]
    }


def test_tenant_mtu_leaves_room_for_vxlan_overhead() -> None:
    intent = raw_intent()
    intent["tenants"]["mtu"] = intent["fabric_mtu"]
    with pytest.raises(ValueError, match="VXLAN overhead exceeds fabric_mtu"):
        validate_semantics(intent)


def test_rejects_duplicate_tenant_route_target() -> None:
    intent = raw_intent()
    intent["tenants"]["vrfs"][1]["route_target"] = intent["tenants"]["vrfs"][0]["route_target"]
    with pytest.raises(ValueError, match="route targets must be unique"):
        validate_semantics(intent)


def test_rejects_tenant_subnet_outside_tenant_range() -> None:
    intent = raw_intent()
    intent["tenants"]["vrfs"][0]["segments"][0]["subnet"] = "10.210.200.0/24"
    with pytest.raises(ValueError, match="outside address_plan.tenants"):
        validate_semantics(intent)


def test_leaf1_hosts_both_tenants_with_loopback_vtep_and_no_learning() -> None:
    intent = load_intent()
    assert [vrf["name"] for vrf in leaf_vrfs(intent, "leaf1")] == ["tenant-a", "tenant-b"]
    script = leaf_tenant_script(intent, "leaf1")
    for vni in (10101, 50001, 10201, 50002):
        assert f"ip link add vx{vni} type vxlan id {vni} local 10.200.0.11 dstport 4789 nolearning" in script
        assert f"ip link set vx{vni} type bridge_slave neigh_suppress on learning off" in script
    assert "ip address replace 10.220.11.1/24 dev br10101" in script
    # The L3VNI SVI carries no IP address (FRR EVPN Linux interface guidance).
    assert not any(
        line.startswith("ip address") and line.endswith(f"dev br{vni}")
        for line in script.splitlines() for vni in (50001, 50002)
    )


def test_tenant_ranges_avoid_backend_and_k3s_ranges() -> None:
    intent = load_intent()
    tenant_range = ipaddress.ip_network(intent["address_plan"]["tenants"])
    for other in [intent["address_plan"][k] for k in ("loopbacks", "hosts", "management")] + intent["address_plan"]["excluded"]:
        assert not tenant_range.overlaps(ipaddress.ip_network(other))


# ---- running lab -----------------------------------------------------------------------------

def ping(source: str, target_ip: str, extra: str = "") -> int:
    command = f"ping -c 2 -W 1 {extra} {target_ip}".replace("  ", " ")
    try:
        return node_result(source, command)["return-code"]
    except AssertionError:
        return 1


def test_every_vni_uses_the_intent_route_targets() -> None:
    """Trap (a): an auto-derived AS:VNI RT on any leaf breaks import across ASes."""
    intent = load_intent()
    for vrf in intent["tenants"]["vrfs"]:
        for segment in vrf["segments"]:
            for vni, rt in ((vrf["l3vni"], vrf["route_target"]), (segment["l2vni"], segment["route_target"])):
                out = node_result(segment["leaf"], f'vtysh -c "show bgp l2vpn evpn vni {vni}"')["stdout"]
                blocks = out.split("VNI: ")[1:]
                assert len(blocks) == 1, f"{segment['leaf']} has {len(blocks)} BGP entries for VNI {vni}:\n{out}"
                imports = out.split("Import Route Target:")[1].split("Export Route Target:")[0].split()
                exports = out.split("Export Route Target:")[1].split()[:1]
                assert imports == [rt] and exports == [rt], f"{segment['leaf']} VNI {vni}: {imports} / {exports}"


def test_same_tenant_endpoints_reach_each_other_across_leaves() -> None:
    eps = endpoints(load_intent())
    for name, ep in eps.items():
        for peer, other in eps.items():
            if peer != name and other["vrf"] == ep["vrf"]:
                assert ping(name, other["ip"]) == 0, f"{name} cannot reach same-tenant {peer}"


def test_different_tenants_are_isolated_even_on_the_same_leaf() -> None:
    eps = endpoints(load_intent())
    assert eps["ta1"]["leaf"] == eps["tb1"]["leaf"]
    for name, ep in eps.items():
        for peer, other in eps.items():
            if other["vrf"] != ep["vrf"]:
                assert ping(name, other["ip"]) != 0, f"{name} ({ep['vrf']}) reached {peer} ({other['vrf']})"


def test_tenants_cannot_reach_backend_rails() -> None:
    intent = load_intent()
    rail_ips = [nic["address"].split("/")[0] for host in intent["hosts"] for nic in host["nics"]]
    for name in endpoints(intent):
        for ip in rail_ips[:2] + rail_ips[-2:]:
            assert ping(name, ip) != 0, f"tenant endpoint {name} reached backend rail {ip}"


def test_tenant_path_mtu_is_exactly_tenant_mtu() -> None:
    intent = load_intent()
    mtu = intent["tenants"]["mtu"]
    eps = endpoints(intent)
    target = eps["ta3"]["ip"]
    assert ping("ta1", target, f"-M do -s {mtu - 28}") == 0, "full-size tenant frame did not cross VXLAN"
    assert ping("ta1", target, f"-M do -s {mtu - 27}") != 0, "frame above tenant MTU was not refused"
