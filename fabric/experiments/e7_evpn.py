"""E7: EVPN-VXLAN tenant VRFs on the front end (EMULATED, FRR 10.2.1 + Linux VXLAN).

Collects control-plane evidence, tenant reachability/isolation, iperf3, the
VXLAN MTU limit, a bounded spine-tap pcap of UDP 4789 with per-tenant VNIs,
and two trap drills that change one runtime knob and restore it:

  rt-auto     leaf3 tenant-a falls back to FRR's auto-derived import RT
  nh-rewrite  spines stop keeping the EVPN next hop unchanged

Usage: python -m fabric.experiments.e7_evpn [evidence|drills|all]
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.experiments.e3.bth_decode import l3_offset, pcap_records
from fabric.experiments.e3.run import background, finish, finish_capture, text
from fabric.intent.schema.validate import load_intent
from fabric.tests.lab import node_result

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e7-results.json"
CAPTURE_DIR = ROOT / "fabric" / "experiments" / "e7"
VXLAN_PORT = 4789


def sh(node: str, command: str) -> dict[str, Any]:
    """Run and record a command; failures are results, not exceptions."""
    try:
        result = node_result(node, command)
    except AssertionError as error:
        return {"node": node, "command": command, "rc": 1, "output": str(error)[-1500:]}
    out = result["stdout"] if isinstance(result["stdout"], str) else json.dumps(result["stdout"])
    return {"node": node, "command": command, "rc": result["return-code"], "output": out}


def vtysh(node: str, command: str) -> dict[str, Any]:
    return sh(node, f'vtysh -c "{command}"')


def endpoints(intent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        ep["name"]: {**ep, "vrf": vrf["name"], "ip": ep["address"].split("/")[0], "l3vni": vrf["l3vni"]}
        for vrf in intent["tenants"]["vrfs"] for ep in vrf["endpoints"]
    }


def reachability(intent: dict[str, Any]) -> list[dict[str, Any]]:
    eps = endpoints(intent)
    rows = []
    rails = {"host1 rail A": "10.210.0.2", "host3 rail A": "10.210.0.10", "host1 rail B": "10.210.1.2"}
    for name, ep in eps.items():
        targets = [(peer, other["ip"], "same tenant" if other["vrf"] == ep["vrf"] else "other tenant")
                   for peer, other in eps.items() if peer != name]
        targets += [(label, ip, "backend rail") for label, ip in rails.items()]
        for peer, ip, kind in targets:
            result = sh(name, f"ping -c 2 -W 1 {ip}")
            expected = kind == "same tenant"
            rows.append({
                "source": name, "source_vrf": ep["vrf"], "target": peer, "target_ip": ip,
                "kind": kind, "reached": result["rc"] == 0, "expected": expected,
                "pass": (result["rc"] == 0) == expected, "command": result["command"],
            })
    return rows


def iperf(source: str, target_ip: str, target: str, port: int) -> dict[str, Any]:
    server = background(target, f"timeout 15 iperf3 -s -1 -p {port}")
    time.sleep(0.5)
    command = f"iperf3 -c {target_ip} -p {port} -t 3 --json"
    document = json.loads(finish(source, background(source, command), timeout=30))
    finish(target, server, timeout=30)
    end = document["end"]
    return {
        "source": source, "target": target, "command": command,
        "received_gbps": end["sum_received"]["bits_per_second"] / 1e9,
        "retransmits": end["sum_sent"].get("retransmits"),
        "label": "EMULATED; shaping state recorded separately",
    }


def mtu_probe(intent: dict[str, Any]) -> list[dict[str, Any]]:
    mtu = intent["tenants"]["mtu"]
    eps = endpoints(intent)
    rows = []
    for size in (mtu - 28, mtu - 27):
        result = sh("ta1", f"ping -c 2 -W 1 -M do -s {size} {eps['ta3']['ip']}")
        rows.append({"payload": size, "ip_packet": size + 28, "rc": result["rc"], "output": result["output"][-400:],
                     "command": result["command"]})
    links = {
        "leaf1 vx10101": sh("leaf1", "ip -d link show vx10101"),
        "leaf1 eth1 (fabric)": sh("leaf1", "ip link show eth1"),
        "ta1 eth1": sh("ta1", "ip link show eth1"),
    }
    return rows + [{"links": links}]


def decode_vxlan(raw: bytes) -> list[dict[str, Any]]:
    packets = []
    for linktype, frame in pcap_records(raw):
        ip = l3_offset(linktype, frame)
        if ip is None or frame[ip + 9] != 17:
            continue
        ihl = (frame[ip] & 0x0F) * 4
        sport, dport = struct.unpack("!HH", frame[ip + ihl:ip + ihl + 4])
        if dport != VXLAN_PORT:
            continue
        vx = ip + ihl + 8
        vni = int.from_bytes(frame[vx + 4:vx + 7], "big")
        inner = vx + 8 + 14
        packets.append({
            "outer_src": ".".join(map(str, frame[ip + 12:ip + 16])),
            "outer_dst": ".".join(map(str, frame[ip + 16:ip + 20])),
            "udp_sport": sport, "vni": vni,
            "inner_src": ".".join(map(str, frame[inner + 12:inner + 16])) if len(frame) >= inner + 20 else None,
            "inner_dst": ".".join(map(str, frame[inner + 16:inner + 20])) if len(frame) >= inner + 20 else None,
        })
    return packets


def capture_tenants(intent: dict[str, Any]) -> dict[str, Any]:
    eps = endpoints(intent)
    out: dict[str, Any] = {}
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    for spine in ("spine1", "spine2"):
        tap = f"{spine}-tap"
        remote = f"/tmp/e7-{spine}-{time.time_ns()}.pcap"
        command = f"timeout 8 tcpdump -n -i any -s 160 -c 60 -w {remote} udp port {VXLAN_PORT}"
        proc = background(tap, command)
        time.sleep(1)
        for source, target in (("ta1", "ta3"), ("tb1", "tb4"), ("tb2", "tb4")):
            sh(source, f"ping -c 5 -i 0.2 -W 1 {eps[target]['ip']}")
        result = finish_capture(tap, proc)
        raw = base64.b64decode(text(tap, f"base64 -w0 {remote}").strip(), validate=True)
        text(tap, f"rm -f -- {remote}")
        path = CAPTURE_DIR / f"vxlan-{spine}.pcap"
        path.write_bytes(raw)
        decoded = decode_vxlan(raw)
        summary: dict[str, int] = {}
        for packet in decoded:
            key = f"VNI {packet['vni']} {packet['outer_src']}->{packet['outer_dst']} inner {packet['inner_src']}->{packet['inner_dst']}"
            summary[key] = summary.get(key, 0) + 1
        out[spine] = {
            "command": command, "file": str(path.relative_to(ROOT)), "bytes": len(raw),
            "tcpdump_stderr": result["stderr"], "packets": len(decoded), "flows": summary,
        }
    return out


def control_plane() -> dict[str, Any]:
    leaves = ("leaf1", "leaf2", "leaf3", "leaf4")
    return {
        "show_evpn_vni": {leaf: vtysh(leaf, "show evpn vni") for leaf in leaves},
        "evpn_type2_leaf3": vtysh("leaf3", "show bgp l2vpn evpn route type 2"),
        "evpn_type5_leaf3": vtysh("leaf3", "show bgp l2vpn evpn route type 5"),
        "evpn_type5_spine1": vtysh("spine1", "show bgp l2vpn evpn route type 5"),
        "evpn_vni_rts_leaf1": vtysh("leaf1", "show bgp l2vpn evpn vni"),
        "vrf_tenant_a_leaf1": vtysh("leaf1", "show bgp vrf tenant-a ipv4 unicast"),
        "vrf_tenant_b_leaf1": vtysh("leaf1", "show bgp vrf tenant-b ipv4 unicast"),
        "vrf_tenant_a_kernel_leaf3": sh("leaf3", "ip route show vrf tenant-a"),
        "evpn_rmac_leaf1": vtysh("leaf1", "show evpn rmac vni all"),
        "evpn_nexthops_leaf1": vtysh("leaf1", "show evpn next-hops vni all"),
        "bridge_fdb_leaf1": sh("leaf1", "bridge fdb show dev vx50001"),
        "bridge_fdb_leaf1_l2": sh("leaf1", "bridge fdb show br br10101"),
        "evpn_summary_spine1": vtysh("spine1", "show bgp l2vpn evpn summary"),
        "default_vrf_leaf1_no_tenant_routes": sh("leaf1", "ip route show 10.220.0.0/16"),
    }


def leaf3_type5_nexthops() -> dict[str, Any]:
    raw = vtysh("leaf3", "show bgp l2vpn evpn route type 5 json")
    try:
        data = json.loads(raw["output"])
    except json.JSONDecodeError:
        return {"raw": raw}
    hops: dict[str, list[str]] = {}
    for rd, prefixes in data.items():
        if not isinstance(prefixes, dict):
            continue
        for prefix, entry in prefixes.items():
            if not isinstance(entry, dict):
                continue
            for path_list in entry.get("paths", []):
                for path in path_list if isinstance(path_list, list) else [path_list]:
                    for nh in path.get("nexthops", []):
                        hops.setdefault(f"{rd} {prefix}", []).append(nh.get("ip"))
    return hops


def drill_rt_auto(intent: dict[str, Any]) -> dict[str, Any]:
    eps = endpoints(intent)
    conf = "router bgp 65103 vrf tenant-a\n address-family l2vpn evpn\n"
    rt = intent["tenants"]["vrfs"][0]["route_target"]
    before = sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}")
    change = sh("leaf3", f"vtysh -c 'configure terminal' -c 'router bgp 65103 vrf tenant-a' -c 'address-family l2vpn evpn' -c 'no route-target import {rt}'")
    time.sleep(4)
    during = {
        "ping": sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}"),
        "leaf3_vrf_rts": vtysh("leaf3", "show bgp vrf tenant-a json"),
        "leaf3_l3vni": vtysh("leaf3", "show bgp l2vpn evpn vni 50001"),
        "leaf3_vrf_routes": sh("leaf3", "ip route show vrf tenant-a"),
    }
    # FRR keeps already-imported routes after an import-RT change; force a
    # re-evaluation (route refresh) to see the steady-state effect.
    refresh = vtysh("leaf3", "clear bgp l2vpn evpn * soft in")
    time.sleep(4)
    during_refreshed = {
        "ping": sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}"),
        "leaf3_vrf_routes": sh("leaf3", "ip route show vrf tenant-a"),
        "leaf1_vrf_routes": sh("leaf1", "ip route show vrf tenant-a"),
    }
    restore = sh("leaf3", f"vtysh -c 'configure terminal' -c 'router bgp 65103 vrf tenant-a' -c 'address-family l2vpn evpn' -c 'route-target import {rt}'")
    time.sleep(4)
    after = sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}")
    return {"description": conf, "before": before, "change": change, "during": during, "refresh": refresh,
            "during_after_refresh": during_refreshed, "restore": restore, "after": after}


def drill_rt_auto_export(intent: dict[str, Any]) -> dict[str, Any]:
    """leaf3 tenant-a exports FRR's auto RT (65103:50001); leaf1 imports only 65000:50001."""
    eps = endpoints(intent)
    rt = intent["tenants"]["vrfs"][0]["route_target"]
    base = "vtysh -c 'configure terminal' -c 'router bgp 65103 vrf tenant-a' -c 'address-family l2vpn evpn'"
    before = sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}")
    change = sh("leaf3", f"{base} -c 'no route-target export {rt}'")
    time.sleep(5)
    during = {
        "ping": sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}"),
        "leaf3_l3vni": vtysh("leaf3", "show bgp l2vpn evpn vni 50001"),
        "leaf1_vrf_routes": sh("leaf1", "ip route show vrf tenant-a"),
        "leaf1_type5_from_leaf3": vtysh("leaf1", "show bgp l2vpn evpn route rd 10.200.0.13:1"),
    }
    restore = sh("leaf3", f"{base} -c 'route-target export {rt}'")
    time.sleep(5)
    after = sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}")
    return {"before": before, "change": change, "during": during, "restore": restore, "after": after}


def drill_nh_rewrite(intent: dict[str, Any]) -> dict[str, Any]:
    eps = endpoints(intent)
    peers = ("PEER_LEAF1", "PEER_LEAF2", "PEER_LEAF3", "PEER_LEAF4")

    def spines(no: bool) -> list[dict[str, Any]]:
        prefix = "no " if no else ""
        out = []
        for spine in ("spine1", "spine2"):
            args = " ".join(f"-c '{prefix}neighbor {p} attribute-unchanged next-hop'" for p in peers)
            out.append(sh(spine, f"vtysh -c 'configure terminal' -c 'router bgp 65000' -c 'address-family l2vpn evpn' {args}"))
            out.append(vtysh(spine, "clear bgp l2vpn evpn * soft out"))
        return out

    before = {"nexthops": leaf3_type5_nexthops(), "ping": sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}")}
    change = spines(True)
    time.sleep(5)
    during = {"nexthops": leaf3_type5_nexthops(), "ping": sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}"),
              "leaf3_vrf_routes": sh("leaf3", "ip route show vrf tenant-a")}
    restore = spines(False)
    time.sleep(5)
    after = {"nexthops": leaf3_type5_nexthops(), "ping": sh("ta1", f"ping -c 2 -W 1 {eps['ta3']['ip']}")}
    return {"before": before, "change": change, "during": during, "restore": restore, "after": after}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", nargs="?", default="all", choices=["evidence", "drills", "all"])
    args = parser.parse_args()
    intent = load_intent()
    results: dict[str, Any] = json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists() else {}
    results.update({"label": "EMULATED (veth + Linux VXLAN/VRF + FRR 10.2.1 EVPN)",
                    "run_at": datetime.now(timezone.utc).isoformat()})
    if args.what in ("evidence", "all"):
        results["control_plane"] = control_plane()
        results["type5_nexthops_leaf3"] = leaf3_type5_nexthops()
        results["reachability"] = reachability(intent)
        eps = endpoints(intent)
        results["iperf3"] = [iperf("ta1", eps["ta3"]["ip"], "ta3", 5601), iperf("tb1", eps["tb4"]["ip"], "tb4", 5602)]
        results["mtu"] = mtu_probe(intent)
        results["capture"] = capture_tenants(intent)
        print(json.dumps({
            "reachability_fail": [r for r in results["reachability"] if not r["pass"]],
            "iperf3": [(r["source"], r["target"], round(r["received_gbps"], 3)) for r in results["iperf3"]],
            "mtu": [(r.get("payload"), r.get("rc")) for r in results["mtu"]],
            "capture": {k: v["flows"] for k, v in results["capture"].items()},
            "type5_nexthops": results["type5_nexthops_leaf3"],
        }, indent=1))
    if args.what in ("drills", "all"):
        results["drill_rt_auto"] = drill_rt_auto(intent)
        results["drill_rt_auto_export"] = drill_rt_auto_export(intent)
        results["drill_nh_rewrite"] = drill_nh_rewrite(intent)
        for name in ("drill_rt_auto", "drill_rt_auto_export", "drill_nh_rewrite"):
            d = results[name]
            print(name, json.dumps({k: (v["rc"] if isinstance(v, dict) and "rc" in v else (v.get("ping", {}).get("rc") if isinstance(v, dict) else None)) for k, v in d.items() if k in ("before", "during", "during_after_refresh", "after")}))
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
