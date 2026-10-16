"""Render the INTENT-ONLY lossless RoCE QoS design.

SONiC output is a config_db.json fragment per switch; table and field names
follow sonic-buildimage 202511 src/sonic-yang-models/doc/Configuration.md and
the 202511 YANG models (sonic-pfcwd, sonic-wred-profile, sonic-port-qos-map,
sonic-buffer-profile). Sources for every value are in fabric/qos/README.md.
None of it has run on a SONiC switch. The Linux render is the part that runs
in the EMULATED lab: DSCP classification on host rail NICs.
"""
from __future__ import annotations

from typing import Any

from jinja2 import Environment

from fabric.tools.headroom import headroom, ieee_response_bytes


def sonic_port(interface: str, stride: int) -> str:
    return f"Ethernet{(int(interface.removeprefix('eth')) - 1) * stride}"


def switch_ports(intent: dict[str, Any], node: str) -> list[tuple[str, dict[str, Any]]]:
    ports = []
    for link in intent["links"]:
        if link["kind"] == "tenant":
            continue  # front-end tenant ports carry no lossless RoCE class
        for endpoint in (link["a"], link["b"]):
            if endpoint["node"] == node:
                ports.append((endpoint["interface"], link))
    return sorted(ports, key=lambda item: int(item[0].removeprefix("eth")))


def cable_m(qos: dict[str, Any], link: dict[str, Any]) -> int:
    return qos["cable_length_m"]["links"].get(link["name"], qos["cable_length_m"][link["kind"]])


def pg_headroom(qos: dict[str, Any], cable: int) -> int:
    """Conservative xoff: the larger of the H3C fixed-response and IEEE 802.3 pause-quanta forms."""
    speed = qos["target"]["port_speed_gbps"]
    row = headroom(speed, cable, qos["pfc"]["mtu_s_bytes"], mtu_r=qos["target"]["port_mtu"])
    ieee = ieee_response_bytes(speed)
    return row.total if ieee is None else max(row.total, row.total - row.response + ieee)


def sonic_config(intent: dict[str, Any], node: str) -> dict[str, Any]:
    qos = intent["qos"]
    classes = qos["classes"]
    by_role = {cls["role"]: cls for cls in classes}
    speed_mbps = qos["target"]["port_speed_gbps"] * 1000
    stride = qos["target"]["sonic_port_stride"]
    map_name = "ROCE"
    dscp_to_tc = {str(dscp): str(by_role["default"]["tc"]) for dscp in range(64)}
    for cls in classes:
        for dscp in cls["dscp"]:
            dscp_to_tc[str(dscp)] = str(cls["tc"])
    tc_to_queue = {str(tc): str(tc) for tc in range(8)}
    tc_to_pg = {str(tc): "0" for tc in range(8)}
    for cls in classes:
        tc_to_queue[str(cls["tc"])] = str(cls["queue"])
        tc_to_pg[str(cls["tc"])] = str(cls["priority_group"])
    pfc_to_queue = {str(prio): str(prio) for prio in range(8)}
    for cls in classes:
        if cls["lossless"]:
            pfc_to_queue[str(cls["pfc_priority"])] = str(cls["queue"])
    pfc_enable = ",".join(str(prio) for prio in sorted(qos["pfc"]["priorities"]))

    schedulers = {}
    for cls in classes:
        entry = {"type": cls["scheduler"]["type"]}
        if "weight" in cls["scheduler"]:
            entry["weight"] = str(cls["scheduler"]["weight"])
        schedulers[f"scheduler.{cls['name']}"] = entry

    ecn = qos["ecn"]
    wred = {
        "ROCE_LOSSLESS": {
            "ecn": "ecn_all",
            "wred_green_enable": "true",
            "wred_yellow_enable": "true",
            "wred_red_enable": "true",
            **{
                f"{color}_{field}": value
                for color in ("green", "yellow", "red")
                for field, value in (
                    ("min_threshold", str(ecn["kmin_bytes"])),
                    ("max_threshold", str(ecn["kmax_bytes"])),
                    ("drop_probability", str(ecn["pmax_percent"])),
                )
            },
        }
    }

    ports = switch_ports(intent, node)
    names = [sonic_port(interface, stride) for interface, _ in ports]
    cable_by_port = {sonic_port(interface, stride): cable_m(qos, link) for interface, link in ports}
    profiles: dict[str, Any] = {}
    buffer_pg: dict[str, Any] = {}
    for port, cable in cable_by_port.items():
        profile = f"pg_lossless_{speed_mbps}_{cable}m_profile"
        profiles[profile] = {
            "pool": "ingress_lossless_pool",
            "xoff": str(pg_headroom(qos, cable)),
            "xon": str(qos["pfc"]["xon_bytes"]),
            "size": str(qos["pfc"]["reserved_bytes"]),
            "static_th": str(qos["pfc"]["xoff_threshold_bytes"]),
        }
        for cls in classes:
            if cls["lossless"]:
                buffer_pg[f"{port}|{cls['priority_group']}"] = {"profile": profile}

    queue: dict[str, Any] = {}
    port_qos: dict[str, Any] = {}
    pfc_wd: dict[str, Any] = {"GLOBAL": {"POLL_INTERVAL": str(qos["pfc_watchdog"]["poll_ms"])}}
    port_table: dict[str, Any] = {}
    for port in names:
        port_table[port] = {"mtu": str(qos["target"]["port_mtu"]), "speed": str(speed_mbps)}
        port_qos[port] = {
            "dscp_to_tc_map": map_name,
            "tc_to_queue_map": map_name,
            "tc_to_pg_map": map_name,
            "pfc_to_queue_map": map_name,
            "pfc_enable": pfc_enable,
            "pfcwd_sw_enable": pfc_enable,
        }
        for cls in classes:
            entry = {"scheduler": f"scheduler.{cls['name']}"}
            if cls["tc"] == ecn["tc"]:
                entry["wred_profile"] = "ROCE_LOSSLESS"
            queue[f"{port}|{cls['queue']}"] = entry
        pfc_wd[port] = {
            "action": qos["pfc_watchdog"]["action"],
            "detection_time": str(qos["pfc_watchdog"]["detection_ms"]),
            "restoration_time": str(qos["pfc_watchdog"]["restoration_ms"]),
        }
    return {
        "PORT": port_table,
        "CABLE_LENGTH": {map_name: {port: f"{cable}m" for port, cable in cable_by_port.items()}},
        "DSCP_TO_TC_MAP": {map_name: dscp_to_tc},
        "TC_TO_QUEUE_MAP": {map_name: tc_to_queue},
        "TC_TO_PRIORITY_GROUP_MAP": {map_name: tc_to_pg},
        "MAP_PFC_PRIORITY_TO_QUEUE": {map_name: pfc_to_queue},
        "PORT_QOS_MAP": port_qos,
        "SCHEDULER": schedulers,
        "WRED_PROFILE": wred,
        "QUEUE": queue,
        "BUFFER_PROFILE": profiles,
        "BUFFER_PG": buffer_pg,
        "PFC_WD": pfc_wd,
    }


def host_bands(qos: dict[str, Any]) -> list[dict[str, Any]]:
    """Strict classes first, then higher TCs; the default class is the last band."""
    ordered = sorted(
        qos["classes"],
        key=lambda cls: (cls["role"] == "default", cls["scheduler"]["type"] != "STRICT", -cls["tc"]),
    )
    return [dict(cls, index=index) for index, cls in enumerate(ordered)]


def host_qos_script(env: Environment, intent: dict[str, Any], host: dict[str, Any]) -> str:
    bands = host_bands(intent["qos"])
    default_band = next(band["index"] for band in bands if band["role"] == "default")
    return env.get_template("host-qos.sh.j2").render(nics=host["nics"], bands=bands, default_band=default_band)
