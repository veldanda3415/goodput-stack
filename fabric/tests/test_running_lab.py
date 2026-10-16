from __future__ import annotations

import ipaddress
from itertools import combinations

from fabric.intent.schema.validate import load_intent
from fabric.tests.lab import node_json, node_result


def routers_by_name(intent: dict) -> dict[str, dict]:
    return {node["name"]: node for node in intent["nodes"]}


def fabric_peers(intent: dict, name: str) -> dict[str, int]:
    routers = routers_by_name(intent)
    peers: dict[str, int] = {}
    for link in intent["links"]:
        if link["kind"] != "fabric":
            continue
        local = next((ep for ep in (link["a"], link["b"]) if ep["node"] == name), None)
        if local is None:
            continue
        remote = next(ep for ep in (link["a"], link["b"]) if ep["node"] != name)
        peers[local["interface"]] = routers[remote["node"]]["asn"]
    return peers


def intended_prefixes(intent: dict) -> set[str]:
    prefixes = {node["loopback"] for node in intent["nodes"]}
    prefixes.update(
        nic["subnet"]
        for host in [*intent["hosts"], *intent.get("vm_hosts", [])]
        for nic in host["nics"]
    )
    return prefixes


def test_bgp_sessions_established_with_expected_asns_and_no_extras() -> None:
    intent = load_intent()
    for node in intent["nodes"]:
        name = node["name"]
        summary = node_json(name, 'vtysh -c "show bgp summary json"')["ipv4Unicast"]
        expected = fabric_peers(intent, name)
        peers = summary["peers"]
        actual_interfaces = set(peers)
        missing = sorted(set(expected) - actual_interfaces)
        unexpected = sorted(actual_interfaces - set(expected))
        if missing or unexpected:
            detail = []
            if missing:
                detail.append(f"missing sessions {missing}")
            if unexpected:
                detail.append(f"unexpected sessions {unexpected}")
            raise AssertionError(f"BGP session down: {name} " + "; ".join(detail))
        if summary["as"] != node["asn"]:
            interface = sorted(expected)[0]
            raise AssertionError(
                f"BGP session down: {name}:{interface} local ASN mismatch "
                f"(expected {node['asn']}, got {summary['as']})"
            )
        for interface, remote_asn in expected.items():
            peer = peers[interface]
            if peer["state"] != "Established":
                raise AssertionError(
                    f"BGP session down: {name}:{interface} "
                    f"state={peer['state']}, remote AS={peer['remoteAs']}, expected {remote_asn}"
                )
            if peer["remoteAs"] != remote_asn:
                raise AssertionError(
                    f"BGP session ASN mismatch: {name}:{interface} "
                    f"remote AS={peer['remoteAs']}, expected {remote_asn}"
                )


def test_ecmp_width_to_every_remote_leaf_loopback() -> None:
    intent = load_intent()
    leaves = [node for node in intent["nodes"] if node["role"] == "leaf"]
    for leaf in leaves:
        for remote in leaves:
            if remote["name"] == leaf["name"]:
                continue
            address = remote["loopback"].split("/")[0]
            routes = node_json(
                leaf["name"], f"ip -j route show {address}/32"
            )
            assert routes, f"{leaf['name']} has no kernel route to {remote['name']} {address}/32"
            nexthops = routes[0].get("nexthops", [])
            assert len(nexthops) == intent["ecmp_width"], (
                f"{leaf['name']} -> {remote['name']} {address}/32 has "
                f"{len(nexthops)} kernel next hops; expected {intent['ecmp_width']}"
            )
            assert all(
                hop.get("via", {}).get("family") == "inet6"
                and ipaddress.IPv6Address(hop["via"]["host"]).is_link_local
                for hop in nexthops
            ), f"{leaf['name']} -> {remote['name']} next hops are not IPv6 link-local"


def test_every_intended_prefix_is_in_each_leaf_bgp_rib() -> None:
    intent = load_intent()
    expected = intended_prefixes(intent)
    for leaf in (node for node in intent["nodes"] if node["role"] == "leaf"):
        routes = node_json(
            leaf["name"], 'vtysh -c "show bgp ipv4 unicast json"'
        )["routes"]
        missing = sorted(expected - set(routes))
        assert not missing, f"{leaf['name']} BGP RIB missing intended prefixes: {missing}"


def test_bfd_is_up_on_every_fabric_link() -> None:
    intent = load_intent()
    for node in intent["nodes"]:
        name = node["name"]
        expected_interfaces = set(fabric_peers(intent, name))
        peers = node_json(name, 'vtysh -c "show bfd peers brief json"')
        actual_interfaces = {peer["interface"] for peer in peers}
        assert actual_interfaces == expected_interfaces, (
            f"{name} BFD interfaces expected {sorted(expected_interfaces)}, "
            f"got {sorted(actual_interfaces)}"
        )
        for peer in peers:
            assert peer["status"] == "up", (
                f"BFD down: {name}:{peer['interface']} peer={peer['peer']} "
                f"status={peer['status']} diagnostic={peer['diagnostic']}"
            )
            assert peer["transmit-interval"] == intent["bfd"]["transmit_ms"]
            assert peer["receive-interval"] == intent["bfd"]["receive_ms"]
            assert peer["detect-multiplier"] == intent["bfd"]["detect_multiplier"]


def test_host_to_host_reachability_matrix_per_rail() -> None:
    intent = load_intent()
    hosts = {host["name"]: host for host in intent["hosts"]}
    for rail in intent["rails"]:
        rail_nics = {
            name: next(nic for nic in host["nics"] if nic["rail"] == rail)
            for name, host in hosts.items()
        }
        for (source_name, source), (target_name, target) in combinations(rail_nics.items(), 2):
            source_ip = source["address"].split("/")[0]
            target_ip = target["address"].split("/")[0]
            result = node_result(
                source_name,
                f"ping -I {source_ip} -c 1 -W 2 {target_ip}",
            )
            assert result["return-code"] == 0, (
                f"host reachability failed on rail {rail}: {source_name} -> {target_name}; "
                f"stdout={result['stdout']!r}; stderr={result['stderr']!r}"
            )


def test_vm_hosts_boot_with_active_rxe_and_reach_each_other_across_spines() -> None:
    intent = load_intent()
    vm_hosts = {host["name"]: host for host in intent["vm_hosts"]}
    source = vm_hosts["vmhost1"]["nics"][0]
    target = vm_hosts["vmhost2"]["nics"][0]
    for name, vm_host in vm_hosts.items():
        output = node_result(name, "vm-exec rdma link show")["stdout"]
        assert f"rxe_{name}_a/1 state ACTIVE" in output, (
            f"{name} has no active SOFT-ROCE device: {output!r}"
        )
    result = node_result(
        "vmhost1",
        f"vm-exec ping -I {source['address'].split('/')[0]} -c 1 -W 2 "
        f"{target['address'].split('/')[0]}",
    )
    assert result["return-code"] == 0, (
        f"VM cross-spine reachability failed: {result['stdout']!r}; {result['stderr']!r}"
    )
