"""E3 driver: SOFT-ROCE verbs traffic across the EMULATED BGP fabric.

Run: python -m fabric.experiments.e3.run <steps>. Subcommands (results land in fabric/experiments/e3-results.json):
  devices   rxe devices, GID tables, chosen RoCE v2 GID index per rail
  rdma      ib_write_bw / ib_read_lat vs iperf3 on three paths, with CPU
  wire      tcpdump on the spine taps, tshark + bth_decode, UDP source-port
            entropy for 1 vs 4 QPs, DSCP/ECN with --tclass
  qos       host tc classification counters for DSCP-marked traffic

Status: `devices` and `qos` ran. `rdma` and `wire` are implemented but
cannot complete on Linux 6.18: rdma_rxe routes and receives only in the
initial network namespace, so verbs traffic from a container rail fails
(E3-soft-roce.md section 0). They are kept for a kernel with rxe netns support.

All numbers come from rdma_rxe (software RoCE v2, CPU-bound, no DCQCN, no
PFC) on veth links. They are not NIC or switch performance.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fabric.experiments.e3.bth_decode import decode, pcap_records, summarize
from fabric.intent.schema.validate import load_intent
from fabric.render.render import rdma_device
from fabric.tests.lab import node_json, node_result

ROOT = Path(__file__).resolve().parents[3]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e3-results.json"
CAPTURE_DIR = ROOT / "fabric" / "experiments" / "e3"
SIZES = (65536, 1048576)
REPEATS = 3
DURATION = 3
TCLASS_DSCP26 = 104  # DSCP 26 << 2, ECN bits 0


def text(node: str, command: str) -> str:
    out = node_result(node, node_command(node, command))["stdout"]
    return out if isinstance(out, str) else json.dumps(out)


def node_command(node: str, command: str) -> str:
    vm_names = {host["name"] for host in load_intent().get("vm_hosts", [])}
    return f"vm-exec {command}" if node in vm_names else command


def background(node: str, command: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "containerlab", "exec", "--runtime", "podman",
            "--name", load_intent()["name"],
            "--label", f"clab-node-name={node}",
            "--format", "json", "--log-level", "error",
            "--cmd", node_command(node, command),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def finish(node: str, process: subprocess.Popen[str], timeout: int = 60) -> str:
    stdout, stderr = process.communicate(timeout=timeout)
    if process.returncode != 0:
        raise RuntimeError(f"containerlab exec failed on {node}: {stderr!r}")
    result = json.loads(stdout)[f"clab-{load_intent()['name']}-{node}"][0]
    out = result["stdout"] if isinstance(result["stdout"], str) else json.dumps(result["stdout"])
    if result["return-code"] != 0:
        raise RuntimeError(f"command failed on {node}: rc={result['return-code']} out={out!r} err={result['stderr']!r}")
    return out


def endpoints() -> dict[str, dict[str, Any]]:
    """(host, rail) -> address, interface, rxe device."""
    out = {}
    intent = load_intent()
    for host in [*intent["hosts"], *intent.get("vm_hosts", [])]:
        for nic in host["nics"]:
            out[f"{host['name']}:{nic['rail']}"] = {
                "host": host["name"],
                "rail": nic["rail"],
                "ip": nic["address"].split("/")[0],
                "interface": nic["interface"],
                "leaf": nic["leaf"],
                "device": rdma_device(host["name"], nic["rail"]),
            }
    return out


PATHS = {
    "same-leaf (host1 A -> host2 A)": ("host1:A", "host2:A"),
    "cross-spine same rail (host1 A -> host3 A)": ("host1:A", "host3:A"),
    "cross-rail (host1 A -> host3 B)": ("host1:A", "host3:B"),
    "vm-cross-spine": ("vmhost1:A", "vmhost2:A"),
}


GID_LINE = re.compile(r"GID\[\s*(\d+)\]:\s+(\S+), (RoCE v[12])")


def roce_v2_gid(endpoint: dict[str, Any]) -> dict[str, Any]:
    info = text(endpoint["host"], f"ibv_devinfo -v -d {endpoint['device']}")
    gids = [{"index": int(i), "gid": gid, "type": kind} for i, gid, kind in GID_LINE.findall(info)]
    wanted = f"::ffff:{endpoint['ip']}"
    match = [g for g in gids if g["gid"] == wanted and g["type"] == "RoCE v2"]
    if len(match) != 1:
        raise RuntimeError(f"no unique RoCE v2 GID {wanted} on {endpoint['device']}: {gids}")
    return {"gids": gids, "roce_v2_index": match[0]["index"], "ibv_devinfo": info}


def cmd_devices(results: dict[str, Any]) -> None:
    eps = endpoints()
    devices: dict[str, Any] = {"rdma_system": text("host1", "rdma system show"),
                               "rdma_link_host1": text("host1", "rdma link show")}
    for key, ep in eps.items():
        gid = roce_v2_gid(ep)
        devices[key] = {**ep, "roce_v2_gid_index": gid["roce_v2_index"], "gids": gid["gids"]}
        if key == "host1:A":
            devices[key]["ibv_devinfo_excerpt"] = "\n".join(gid["ibv_devinfo"].splitlines()[:40])
    results["devices"] = devices


def perftest(tool: str, src: dict[str, Any], dst: dict[str, Any], size: int, extra: str = "") -> dict[str, Any]:
    src_gid, dst_gid = roce_v2_gid(src)["roce_v2_index"], roce_v2_gid(dst)["roce_v2_index"]
    mode = f"-D {DURATION} --report_gbits" if tool == "ib_write_bw" else "-n 1000"
    server_cmd = f"timeout 40 {tool} -d {dst['device']} -x {dst_gid} -s {size} {mode} -F {extra}".strip()
    client_cmd = (f"{tool} -d {src['device']} -x {src_gid} -s {size} {mode} -F "
                  f"--bind_source_ip {src['ip']} {extra} {dst['ip']}")
    if tool == "ib_write_bw":
        client_cmd = client_cmd.replace(" -F ", " -F --cpu_util ", 1)
    server = background(dst["host"], server_cmd)
    time.sleep(1.5)
    mpstat = background(src["host"], f"mpstat {DURATION}  1") if tool == "ib_write_bw" else None
    client_out = text(src["host"], client_cmd)
    server_out = finish(dst["host"], server)
    mp_out = finish(src["host"], mpstat) if mpstat else None
    return {
        "server_command": server_cmd,
        "client_command": client_cmd,
        "parsed": parse_perftest(tool, client_out, size),
        "client_output": client_out,
        "server_output_tail": "\n".join(server_out.splitlines()[-4:]),
        "mpstat": parse_mpstat(mp_out) if mp_out else None,
        "mpstat_raw": mp_out,
    }


def parse_perftest(tool: str, output: str, size: int) -> dict[str, Any]:
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0] == str(size):
            values = [float(v) for v in fields[1:] if re.fullmatch(r"[0-9.]+", v)]
            if tool == "ib_write_bw":
                # bytes iterations BWpeak BWavg MsgRate [cpu_util columns]
                return {"iterations": values[0], "bw_peak_gbps": values[1], "bw_avg_gbps": values[2],
                        "msg_rate_mpps": values[3], "extra": values[4:]}
            # bytes iterations t_min t_max t_typical t_avg t_stdev p99 p99.9 (usec)
            return {"iterations": values[0], "t_min_us": values[1], "t_max_us": values[2],
                    "t_typical_us": values[3], "t_avg_us": values[4], "t_stdev_us": values[5],
                    "p99_us": values[6] if len(values) > 6 else None,
                    "p999_us": values[7] if len(values) > 7 else None}
    raise RuntimeError(f"no result line for size {size} in {tool} output:\n{output}")


def parse_mpstat(output: str) -> dict[str, float]:
    header = None
    for line in output.splitlines():
        fields = line.split()
        if "%usr" in fields:
            header = fields
        if header and fields and fields[0].startswith("Average") and fields[1] == "all":
            return {name: float(value) for name, value in zip(header[2:], fields[2:])}
    raise RuntimeError(f"no mpstat average line:\n{output}")


def iperf(src: dict[str, Any], dst: dict[str, Any], size: int) -> dict[str, Any]:
    server = background(dst["host"], f"timeout 30 iperf3 -s -1 -B {dst['ip']}")
    time.sleep(1)
    command = f"iperf3 -c {dst['ip']} -B {src['ip']} -t {DURATION} -l {size} --json"
    result = node_result(src["host"], node_command(src["host"], command))["stdout"]
    data = result if isinstance(result, dict) else json.loads(result)
    finish(dst["host"], server)
    return {
        "command": command,
        "received_gbps": data["end"]["sum_received"]["bits_per_second"] / 1e9,
        "sender_cpu_total": data["end"]["cpu_utilization_percent"]["host_total"],
        "receiver_cpu_total": data["end"]["cpu_utilization_percent"]["remote_total"],
    }


def cmd_rdma(results: dict[str, Any], selected_paths: list[str] | None = None) -> None:
    eps = endpoints()
    vm_eps = {key: endpoint for key, endpoint in eps.items() if endpoint["host"].startswith("vmhost")}
    runs: dict[str, Any] = {
        "nproc": text("vmhost1", "nproc").strip(),
        "rxe_counters_before": {
            key: rdma_counters(endpoint) for key, endpoint in vm_eps.items()
        },
    }
    labels = selected_paths or list(PATHS)
    for label in labels:
        src_key, dst_key = PATHS[label]
        src, dst = eps[src_key], eps[dst_key]
        path = {"traceroute": text(src["host"], f"traceroute -n -q 1 -s {src['ip']} {dst['ip']}")}
        for size in SIZES:
            for tool in ("ib_write_bw", "ib_read_lat"):
                path[f"{tool}_{size}"] = [perftest(tool, src, dst, size) for _ in range(REPEATS)]
                print(label, tool, size, [r["parsed"] for r in path[f"{tool}_{size}"]])
            path[f"iperf3_{size}"] = [iperf(src, dst, size) for _ in range(REPEATS)]
            print(label, "iperf3", size, [r["received_gbps"] for r in path[f"iperf3_{size}"]])
        runs[label] = path
    runs["rxe_counters_after"] = {
        key: rdma_counters(endpoint) for key, endpoint in vm_eps.items()
    }
    results["rdma"] = runs


def rdma_counters(endpoint: dict[str, Any]) -> dict[str, int]:
    output = text(
        endpoint["host"],
        f"rdma statistic show link {endpoint['device']}/1",
    )
    counters = {
        name: int(value)
        for name, value in re.findall(r"^\s*(sent_pkts|rcvd_pkts)\s+(\d+)\s*$", output, re.M)
    }
    if set(counters) != {"sent_pkts", "rcvd_pkts"}:
        raise RuntimeError(f"missing rxe packet counters for {endpoint['device']}:\n{output}")
    return counters


def tx_bytes(node: str, interface: str) -> int:
    return int(node_json(node, f"ip -j -s link show dev {interface}")[0]["stats64"]["tx"]["bytes"])


def uplinks(leaf: str) -> dict[str, str]:
    """leaf interface -> spine name, from intent."""
    out = {}
    for link in load_intent()["links"]:
        if link["kind"] == "fabric" and link["b"]["node"] == leaf:
            out[link["b"]["interface"]] = link["a"]["node"]
        elif link["kind"] == "fabric" and link["a"]["node"] == leaf:
            out[link["a"]["interface"]] = link["b"]["node"]
    return out


def spine_port_to(spine: str, leaf: str) -> str:
    for link in load_intent()["links"]:
        ends = {link["a"]["node"]: link["a"]["interface"], link["b"]["node"]: link["b"]["interface"]}
        if link["kind"] == "fabric" and spine in ends and leaf in ends:
            return ends[spine]
    raise RuntimeError(f"no link {spine}-{leaf}")


def capture_run(src: dict[str, Any], dst: dict[str, Any], qps: int, tclass: int | None,
                packets: int, snaplen: int, tag: str) -> dict[str, Any]:
    """Run ib_write_bw while capturing on both spines' ports toward the source leaf."""
    ups = uplinks(src["leaf"])
    before = {iface: tx_bytes(src["leaf"], iface) for iface in ups}
    taps = {}
    for spine in sorted(set(ups.values())):
        port = spine_port_to(spine, src["leaf"])
        pcap = f"/tmp/e3-{tag}-{spine}.pcap"
        cmd = f"timeout {DURATION + 8} tcpdump -n -i {port} -s {snaplen} -c {packets} -w {pcap} udp port 4791"
        taps[spine] = {"port": port, "pcap": pcap, "command": cmd, "proc": background(f"{spine}-tap", cmd)}
    time.sleep(1.5)
    extra = f"-q {qps}" + (f" --tclass {tclass}" if tclass is not None else "")
    run = perftest("ib_write_bw", src, dst, 65536, extra)
    after = {iface: tx_bytes(src["leaf"], iface) for iface in ups}
    out: dict[str, Any] = {"qps": qps, "tclass": tclass, "perftest": run["parsed"],
                           "client_command": run["client_command"],
                           "leaf_tx_delta": {f"{src['leaf']}:{i} (to {ups[i]})": after[i] - before[i] for i in ups},
                           "spines": {}}
    for spine, tap in taps.items():
        stdout, _ = tap["proc"].communicate(timeout=DURATION + 20)  # tcpdump exits 124 on timeout
        raw = base64.b64decode(text(f"{spine}-tap", f"base64 -w0 {tap['pcap']}").strip() or "")
        local = CAPTURE_DIR / f"{tag}-{spine}.pcap"
        local.write_bytes(raw)
        decoded = [p for lt, frame in pcap_records(raw) if (p := decode(frame, lt))] if raw else []
        out["spines"][spine] = {"command": tap["command"], "pcap": str(local.relative_to(ROOT)),
                                "pcap_bytes": len(raw), "summary": summarize(decoded)}
    return out


def cmd_wire(results: dict[str, Any]) -> None:
    eps = endpoints()
    src, dst = eps["vmhost1:A"], eps["vmhost2:A"]
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    wire: dict[str, Any] = {}
    # Decode sample: full frames, DSCP 26 marking, at most 400 packets per spine (< 2 MB).
    wire["tclass104_1qp"] = capture_run(src, dst, 1, TCLASS_DSCP26, 400, 0, "tclass104-1qp")
    # Entropy: headers only, more packets, 1 vs 4 QPs, three repeats each.
    for qps in (1, 4):
        wire[f"entropy_{qps}qp"] = [
            capture_run(src, dst, qps, None, 4000, 96, f"entropy-{qps}qp-r{r}") for r in range(1, REPEATS + 1)
        ]
    sample = wire["tclass104_1qp"]["spines"]
    busiest = max(sample, key=lambda s: sample[s]["pcap_bytes"])
    tap, pcap = f"{busiest}-tap", sample[busiest]["pcap"]
    remote = f"/tmp/e3-tclass104-1qp-{busiest}.pcap"
    fields = ("-T fields -E header=y -e frame.number -e ip.src -e ip.dst -e ip.dsfield.dscp "
              "-e ip.dsfield.ecn -e udp.srcport -e infiniband.bth.opcode -e infiniband.bth.destqp "
              "-e infiniband.bth.psn -e infiniband.bth.a -e infiniband.invariant.crc")
    wire["tshark"] = {
        "busiest_spine": busiest,
        "pcap": pcap,
        "version": text(tap, "tshark --version").splitlines()[0],
        "fields_command": f"tshark -r {remote} -d udp.port==4791,infiniband -c 12 {fields}",
        "fields": text(tap, f"tshark -r {remote} -d udp.port==4791,infiniband -c 12 {fields}"),
        "verbose_command": f"tshark -r {remote} -d udp.port==4791,infiniband -c 1 -V -O ip,udp,infiniband",
        "verbose": text(tap, f"tshark -r {remote} -d udp.port==4791,infiniband -c 1 -V -O ip,udp,infiniband"),
    }
    results["wire"] = wire


def tc_class_packets(host: str, interface: str) -> dict[str, int]:
    stats = node_json(host, f"tc -s -j class show dev {interface}")
    return {entry["handle"]: int(entry["stats"]["packets"]) for entry in stats}


def cmd_qos(results: dict[str, Any]) -> None:
    """Host tc classification check. Uses iperf3 --tos because SOFT-ROCE cannot
    send from container network namespaces on this kernel (see feasibility)."""
    eps = endpoints()
    src, dst = eps["host1:A"], eps["host3:A"]
    checks: dict[str, Any] = {"qdisc": text("host1", f"tc qdisc show dev {src['interface']}"),
                              "filters": text("host1", f"tc filter show dev {src['interface']}")}
    for label, tos in (("unmarked", 0), ("dscp26_tos104", 104), ("dscp48_tos192", 192)):
        before = tc_class_packets("host1", src["interface"])
        server = background(dst["host"], f"timeout 20 iperf3 -s -1 -B {dst['ip']}")
        time.sleep(1)
        command = f"iperf3 -c {dst['ip']} -B {src['ip']} -t 2 --tos {tos} --json"
        node_result("host1", command)
        finish(dst["host"], server)
        after = tc_class_packets("host1", src["interface"])
        checks[label] = {"command": command,
                         "class_packet_delta": {k: after[k] - before.get(k, 0) for k in after}}
        print(label, checks[label]["class_packet_delta"])
    results["qos"] = checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("steps", nargs="+", choices=["devices", "rdma", "wire", "qos"])
    parser.add_argument("--path", action="append", choices=PATHS, dest="paths")
    args = parser.parse_args()
    results = json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists() else {}
    commands = {"devices": cmd_devices, "rdma": cmd_rdma, "wire": cmd_wire, "qos": cmd_qos}
    for step in args.steps:
        if step == "rdma":
            cmd_rdma(results, args.paths)
        else:
            commands[step](results)
        results.setdefault("timestamps", {})[step] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {step} to {RESULT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
