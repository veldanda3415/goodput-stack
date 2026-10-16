from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml


INTENT_PATH = Path(__file__).resolve().parents[1] / "fabric.yaml"
SCHEMA_PATH = Path(__file__).with_name("fabric.schema.json")


def load_intent(path: Path = INTENT_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        intent = yaml.safe_load(stream)
    with SCHEMA_PATH.open(encoding="utf-8") as stream:
        schema = json.load(stream)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(intent)
    validate_semantics(intent)
    return intent


def validate_semantics(intent: dict[str, Any]) -> None:
    nodes = {node["name"]: node for node in intent["nodes"]}
    hosts = {host["name"]: host for host in intent["hosts"]}
    vm_hosts = {host["name"]: host for host in intent.get("vm_hosts", [])}
    if len(nodes) != len(intent["nodes"]):
        raise ValueError("node names must be unique")
    if len(hosts) != len(intent["hosts"]):
        raise ValueError("host names must be unique")
    if len(vm_hosts) != len(intent.get("vm_hosts", [])):
        raise ValueError("VM host names must be unique")
    host_names = set(hosts) | set(vm_hosts)
    if len(host_names) != len(hosts) + len(vm_hosts):
        raise ValueError("container and VM host names must not overlap")
    tenant_endpoints = {
        endpoint["name"]: endpoint
        for vrf in intent.get("tenants", {}).get("vrfs", [])
        for endpoint in vrf["endpoints"]
    }
    all_names = set(nodes) | host_names
    if len(all_names) != len(nodes) + len(hosts) + len(vm_hosts):
        raise ValueError("node and host names must not overlap")
    if all_names & set(tenant_endpoints):
        raise ValueError("tenant endpoint names must not overlap nodes or hosts")
    all_names |= set(tenant_endpoints)

    spines = [node for node in nodes.values() if node["role"] == "spine"]
    leaves = [node for node in nodes.values() if node["role"] == "leaf"]
    if len(spines) != 2 or len(leaves) != 4:
        raise ValueError(f"expected 2 spines and 4 leaves; found {len(spines)} and {len(leaves)}")
    leaf_asns = [node["asn"] for node in leaves]
    if len(set(leaf_asns)) != len(leaf_asns):
        raise ValueError("leaf ASNs must be unique")
    if intent["bgp"]["spine_asn"] in leaf_asns:
        raise ValueError("spine and leaf ASNs must be distinct")
    if any(node["asn"] != intent["bgp"]["spine_asn"] for node in spines):
        raise ValueError("all spines must use bgp.spine_asn")
    if any(node["asn"] != intent["bgp"]["leaf_asn_base"] + int(node["name"][4:]) - 1 for node in leaves):
        raise ValueError("leaf ASN must match bgp.leaf_asn_base and leaf index")
    if len({str(ipaddress.ip_interface(node["loopback"]).ip) for node in nodes.values()}) != len(nodes):
        raise ValueError("router loopback addresses must be unique")

    all_networks: list[tuple[str, ipaddress.IPv4Network]] = []
    plan = intent["address_plan"]
    for label in ("loopbacks", "hosts", "management", "tenants", "excluded"):
        if label not in plan:
            continue
        values = plan[label] if isinstance(plan[label], list) else [plan[label]]
        all_networks.extend((f"address_plan.{label}", ipaddress.ip_network(value, strict=False)) for value in values)
    for index, (left_name, left) in enumerate(all_networks):
        for right_name, right in all_networks[index + 1:]:
            if left.overlaps(right) and not (left_name.startswith("address_plan.excluded") or right_name.startswith("address_plan.excluded")):
                raise ValueError(f"address ranges overlap: {left_name} {left} and {right_name} {right}")
    excluded = [ipaddress.ip_network(value) for value in plan["excluded"]]
    loopback_range = ipaddress.ip_network(plan["loopbacks"])
    host_range = ipaddress.ip_network(plan["hosts"])
    for node in nodes.values():
        address = ipaddress.ip_interface(node["loopback"])
        if address.version != 4 or address.ip not in loopback_range or address.network.prefixlen != 32:
            raise ValueError(f"{node['name']} loopback {address} is outside address_plan.loopbacks {loopback_range}")
    for name, image in intent["images"].items():
        if not re.fullmatch(r".+:[^/@]+@sha256:[0-9a-f]{64}", image):
            raise ValueError(f"images.{name} must have a version tag and sha256 digest")
    for name, subnet in all_networks:
        if name.startswith("address_plan.excluded"):
            continue
        if any(subnet.overlaps(blocked) for blocked in excluded):
            raise ValueError(f"{name} {subnet} overlaps excluded network {next(n for n in excluded if subnet.overlaps(n))}")

    endpoint_owners: dict[tuple[str, str], str] = {}
    link_names: set[str] = set()
    for link in intent["links"]:
        if link["name"] in link_names:
            raise ValueError(f"duplicate link name: {link['name']}")
        link_names.add(link["name"])
        for endpoint in (link["a"], link["b"]):
            node_name, interface = endpoint["node"], endpoint["interface"]
            if node_name not in all_names:
                raise ValueError(f"link {link['name']} refers to missing endpoint {node_name}")
            key = (node_name, interface)
            if key in endpoint_owners:
                raise ValueError(f"interface {node_name}:{interface} appears in links {endpoint_owners[key]} and {link['name']}")
            endpoint_owners[key] = link["name"]
        if link["kind"] == "fabric" and any(endpoint["node"] not in nodes for endpoint in (link["a"], link["b"])):
            raise ValueError(f"fabric link {link['name']} must connect router nodes")
        if link["kind"] == "host" and not any(endpoint["node"] in host_names for endpoint in (link["a"], link["b"])):
            raise ValueError(f"host link {link['name']} must include a host")
        if link["kind"] == "tenant" and not any(endpoint["node"] in tenant_endpoints for endpoint in (link["a"], link["b"])):
            raise ValueError(f"tenant link {link['name']} must include a tenant endpoint")

    subnet_networks: list[tuple[str, ipaddress.IPv4Network]] = []
    vm_macs: set[str] = set()
    for host in [*hosts.values(), *vm_hosts.values()]:
        is_vm_host = host["name"] in vm_hosts
        if is_vm_host:
            if len(host["nics"]) != 1 or host["nics"][0]["rail"] not in intent["rails"]:
                raise ValueError(f"{host['name']} must have exactly one NIC on a declared rail")
            if not 128 <= host["memory_mib"] <= 1024:
                raise ValueError(f"{host['name']} memory_mib must be between 128 and 1024")
            if not 1 <= host["vcpus"] <= 4:
                raise ValueError(f"{host['name']} vcpus must be between 1 and 4")
            macs = [host["management_mac"], *(nic["mac"] for nic in host["nics"])]
            normalized_macs = [mac.lower() for mac in macs]
            if len(set(normalized_macs)) != len(normalized_macs) or any(mac in vm_macs for mac in normalized_macs):
                raise ValueError(f"{host['name']} has a duplicate VM MAC address")
            vm_macs.update(normalized_macs)
        else:
            if len(host["nics"]) != len(intent["rails"]):
                raise ValueError(f"{host['name']} must have exactly one NIC per rail")
            rails = [nic["rail"] for nic in host["nics"]]
            if set(rails) != set(intent["rails"]) or len(set(rails)) != len(rails):
                raise ValueError(f"{host['name']} must have exactly one NIC for each rail {intent['rails']}")
        for nic in host["nics"]:
            if nic["leaf"] not in nodes or nodes[nic["leaf"]]["role"] != "leaf":
                raise ValueError(f"{host['name']} {nic['rail']} NIC references non-leaf {nic['leaf']}")
            net = ipaddress.ip_network(nic["subnet"], strict=True)
            addr = ipaddress.ip_interface(nic["address"])
            if addr.version != 4 or addr.ip not in net or ipaddress.ip_address(nic["gateway"]) not in net:
                raise ValueError(f"{host['name']} {nic['rail']} address and gateway must belong to {net}")
            if addr.ip == ipaddress.ip_address(nic["gateway"]):
                raise ValueError(f"{host['name']} {nic['rail']} address duplicates its gateway")
            if ipaddress.ip_address(nic["gateway"]) != net.network_address + 1:
                raise ValueError(f"{host['name']} {nic['rail']} gateway must be the first usable address in {net}")
            if addr.ip == net.network_address + 1:
                raise ValueError(f"{host['name']} {nic['rail']} address is reserved for the leaf gateway")
            if not net.subnet_of(host_range):
                raise ValueError(f"{host['name']} {nic['rail']} subnet {net} is outside address_plan.hosts {host_range}")
            subnet_networks.append((f"{host['name']} {nic['rail']}", net))
            matches = []
            for link in intent["links"]:
                endpoints = (link["a"], link["b"])
                host_endpoint = next((ep for ep in endpoints if ep["node"] == host["name"]), None)
                leaf_endpoint = next((ep for ep in endpoints if ep["node"] == nic["leaf"]), None)
                if (
                    link["kind"] == "host"
                    and host_endpoint is not None
                    and leaf_endpoint is not None
                    and host_endpoint["interface"] == nic["interface"]
                ):
                    matches.append(link)
            if len(matches) != 1:
                raise ValueError(f"{host['name']} {nic['rail']} NIC needs exactly one matching host link")

    for index, (left_name, left) in enumerate(subnet_networks):
        for right_name, right in subnet_networks[index + 1:]:
            if left.overlaps(right):
                raise ValueError(f"host subnets overlap: {left_name} {left} and {right_name} {right}")
            if any(left.overlaps(network) for network in excluded):
                raise ValueError(f"host subnet {left} overlaps an excluded network")
    for subnet_name, subnet in subnet_networks:
        for reserved_name in ("loopbacks", "management"):
            reserved = ipaddress.ip_network(plan[reserved_name], strict=False)
            if subnet.overlaps(reserved):
                raise ValueError(f"host subnet {subnet_name} {subnet} overlaps {reserved_name} {reserved}")

    if intent["ecmp_width"] != len(spines):
        raise ValueError(f"ecmp_width must equal spine count ({len(spines)})")
    for tap in intent["capture_taps"]:
        if tap not in nodes:
            raise ValueError(f"capture tap {tap} is not a router node")
    shaping = intent.get("lab_shaping")
    if shaping:
        if shaping["pin_rail"] not in intent["rails"]:
            raise ValueError(f"lab_shaping.pin_rail {shaping['pin_rail']} is not a declared rail")
        if shaping["limit_bytes"] < shaping["burst_bytes"]:
            raise ValueError("lab_shaping.limit_bytes must be at least burst_bytes")
    validate_tenants(intent)
    validate_qos(intent)


def validate_tenants(intent: dict[str, Any]) -> None:
    """EVPN-VXLAN front-end tenancy: VNI/RT/subnet uniqueness, MTU, links."""
    tenancy = intent.get("tenants")
    if not tenancy:
        return
    plan = intent["address_plan"]
    if "tenants" not in plan:
        raise ValueError("tenants need address_plan.tenants")
    tenant_range = ipaddress.ip_network(plan["tenants"])
    overhead = 50  # outer Ethernet 14 + IPv4 20 + UDP 8 + VXLAN 8 (RFC 7348 section 5)
    if tenancy["mtu"] + overhead > intent.get("fabric_mtu", 1500):
        raise ValueError(
            f"tenants.mtu {tenancy['mtu']} + {overhead} B VXLAN overhead exceeds fabric_mtu "
            f"{intent.get('fabric_mtu', 1500)}"
        )
    leaves = {node["name"] for node in intent["nodes"] if node["role"] == "leaf"}
    vnis: list[int] = []
    tables: list[int] = []
    rts: list[str] = []
    subnets: list[ipaddress.IPv4Network] = []
    tenant_links = {
        endpoint["node"]: link
        for link in intent["links"] if link["kind"] == "tenant"
        for endpoint in (link["a"], link["b"])
    }
    for vrf in tenancy["vrfs"]:
        vnis.append(vrf["l3vni"])
        tables.append(vrf["table"])
        rts.append(vrf["route_target"])
        segment_leaves = [segment["leaf"] for segment in vrf["segments"]]
        if len(set(segment_leaves)) != len(segment_leaves):
            raise ValueError(f"{vrf['name']} has more than one segment on a leaf")
        for segment in vrf["segments"]:
            if segment["leaf"] not in leaves:
                raise ValueError(f"{vrf['name']} segment references non-leaf {segment['leaf']}")
            vnis.append(segment["l2vni"])
            rts.append(segment["route_target"])
            subnet = ipaddress.ip_network(segment["subnet"])
            if not subnet.subnet_of(tenant_range):
                raise ValueError(f"{vrf['name']} subnet {subnet} is outside address_plan.tenants {tenant_range}")
            subnets.append(subnet)
        for endpoint in vrf["endpoints"]:
            segment = next((seg for seg in vrf["segments"] if seg["leaf"] == endpoint["leaf"]), None)
            if segment is None:
                raise ValueError(f"{endpoint['name']} is on {endpoint['leaf']} where {vrf['name']} has no segment")
            address = ipaddress.ip_interface(endpoint["address"])
            if address.network != ipaddress.ip_network(segment["subnet"]) or address.ip == address.network.network_address + 1:
                raise ValueError(f"{endpoint['name']} address {address} must be a host in {segment['subnet']} other than the gateway")
            link = tenant_links.get(endpoint["name"])
            if link is None or not any(ep["node"] == endpoint["leaf"] for ep in (link["a"], link["b"])):
                raise ValueError(f"{endpoint['name']} needs a tenant link to {endpoint['leaf']}")
    for label, values in (("VNI", vnis), ("VRF table", tables), ("route target", rts)):
        if len(set(values)) != len(values):
            raise ValueError(f"tenant {label}s must be unique")
    for index, left in enumerate(subnets):
        if any(left.overlaps(right) for right in subnets[index + 1:]):
            raise ValueError(f"tenant subnet {left} overlaps another tenant subnet")


def validate_qos(intent: dict[str, Any]) -> None:
    """Semantic checks for the INTENT-ONLY lossless RoCE QoS design."""
    qos = intent["qos"]
    classes = qos["classes"]
    roles = [cls["role"] for cls in classes]
    for role in ("roce", "cnp", "default"):
        if roles.count(role) != 1:
            raise ValueError(f"qos needs exactly one {role} class; found {roles.count(role)}")
    if len({cls["name"] for cls in classes}) != len(classes):
        raise ValueError("qos class names must be unique")
    if len({cls["tc"] for cls in classes}) != len(classes):
        raise ValueError("qos classes must use distinct traffic classes")
    dscps = [dscp for cls in classes for dscp in cls["dscp"]]
    if len(set(dscps)) != len(dscps):
        raise ValueError("a DSCP value is mapped to more than one qos class")
    by_role = {cls["role"]: cls for cls in classes}
    if by_role["default"]["dscp"]:
        raise ValueError("the default class takes unmapped DSCPs; list none")
    if not by_role["cnp"]["dscp"] or by_role["cnp"]["scheduler"]["type"] != "STRICT":
        raise ValueError("the CNP class needs a DSCP and a STRICT scheduler")
    if by_role["cnp"]["lossless"]:
        raise ValueError("the CNP class must not be lossless")
    pfc_priorities = set(qos["pfc"]["priorities"])
    for cls in classes:
        if cls["scheduler"]["type"] != "STRICT" and "weight" not in cls["scheduler"]:
            raise ValueError(f"qos class {cls['name']} needs a scheduler weight")
        if cls["lossless"]:
            if "pfc_priority" not in cls or cls["pfc_priority"] not in pfc_priorities:
                raise ValueError(f"lossless class {cls['name']} has no PFC priority enabled in qos.pfc.priorities")
            if cls["priority_group"] == 0:
                raise ValueError(f"lossless class {cls['name']} must not share lossy priority group 0")
        elif "pfc_priority" in cls:
            raise ValueError(f"lossy class {cls['name']} must not set pfc_priority")
    lossless_tcs = {cls["tc"] for cls in classes if cls["lossless"]}
    if {cls["pfc_priority"] for cls in classes if cls["lossless"]} != pfc_priorities:
        raise ValueError("qos.pfc.priorities must match the lossless classes")
    ecn = qos["ecn"]
    if ecn["tc"] not in lossless_tcs:
        raise ValueError("qos.ecn.tc must be a lossless traffic class")
    if ecn["kmin_bytes"] >= ecn["kmax_bytes"]:
        raise ValueError("ECN Kmin must be below Kmax")
    if ecn["kmax_bytes"] >= qos["pfc"]["xoff_threshold_bytes"]:
        raise ValueError("ECN Kmax must be below the PFC XOFF threshold so ECN marks before PFC pauses")
    wd = qos["pfc_watchdog"]
    if wd["detection_ms"] < wd["poll_ms"] or wd["restoration_ms"] < wd["poll_ms"]:
        raise ValueError("PFC watchdog detection/restoration must be >= poll interval")
    if qos["target"]["roce_mtu"] > qos["target"]["port_mtu"]:
        raise ValueError("RoCE MTU must fit in the port MTU")
    link_names = {link["name"] for link in intent["links"]}
    unknown = sorted(set(qos["cable_length_m"]["links"]) - link_names)
    if unknown:
        raise ValueError(f"qos.cable_length_m.links names unknown links {unknown}")
