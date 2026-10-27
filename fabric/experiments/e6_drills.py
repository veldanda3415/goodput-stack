"""E6: failure drills under collective load (EMULATED, shaped uplinks).

Load: ring over the four rail-A hosts, L4 ECMP hash, 16 flows/pair,
`iperf3 -t 30`, synchronized start (see e5_shaped), receiver timeline from
0.5 s server intervals. In parallel: ping probes per rail and per tenant
(`ping -D -i 0.1`) and `ip -ts monitor route nexthop` on leaf1/leaf2/leaf3 for
data-plane reconvergence timestamps. Faults are injected at T0+INJECT and
restored at T0+RESTORE inside the lab (ip link / tc netem); state is restored
from the rendered shaping scripts, then the run waits for BGP/BFD to be
fully up before the next run.

Usage: python -m fabric.experiments.e6_drills [all|baseline|<fault> ...] [--repeats N]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import random
import re
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fabric.experiments.e3.run import background, finish
from fabric.experiments.e5_shaped import (
    SYNC_SCRIPT,
    install_sync,
    link_delta,
    link_snapshot,
    parse_sync,
    refuse_probes,
    set_routing,
)
from fabric.intent.schema.validate import load_intent
from fabric.render.shaping import collective_pairs, rail_hosts
from fabric.tests.lab import node_json, node_result
from fabric.tools import shaping

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "fabric" / "experiments" / "e6-results.json"
DURATION = 30
INTERVAL = 0.5
INJECT = 10.0
RESTORE = 20.0
FLOWS = 16
PORT_BASE = 8100
SYNC_LEAD = 2.0
PROBES = {
    # name: (node, source ip, target ip, what it represents)
    "railA host1->host3 (leaf1->leaf2)": ("host1", "10.210.0.2", "10.210.0.10"),
    "railB host1->host3 (leaf3->leaf4)": ("host1", "10.210.1.2", "10.210.1.10"),
    "railA host3->host4 (same leaf2)": ("host3", "10.210.0.10", "10.210.0.14"),
    "tenant-a ta1->ta3 (leaf1->leaf3)": ("ta1", None, "10.220.13.10"),
    "tenant-b tb1->tb4 (leaf1->leaf4)": ("tb1", None, "10.220.24.10"),
    "tenant-b tb2->tb4 (leaf2->leaf4)": ("tb2", None, "10.220.24.10"),
}
MONITORS = ("leaf1", "leaf2", "leaf3")


def sh(node: str, command: str) -> dict[str, Any]:
    started = time.time()
    try:
        result = node_result(node, command)
        return {"node": node, "command": command, "t": started, "rc": result["return-code"]}
    except AssertionError as error:
        return {"node": node, "command": command, "t": started, "rc": 1, "error": str(error)[-400:]}


def restore_shaping(nodes: list[str]) -> None:
    for node in nodes:
        shaping.run_script(node, shaping.BUILD / f"{node}-shape-on.sh")


# ---- faults: inject(), restore() -> list of executed commands -------------------------------

def fault_link_down() -> tuple[Callable, Callable, dict]:
    meta = {"link": "spine1:eth1 <-> leaf1:eth1", "how": "ip link set eth1 down on spine1 (carrier loss on both ends)"}
    return (lambda: [sh("spine1", "ip link set eth1 down")],
            lambda: [sh("spine1", "ip link set eth1 up")], meta)


def fault_silent_loss() -> tuple[Callable, Callable, dict]:
    meta = {"link": "spine1:eth1 <-> leaf1:eth1", "how": "tc netem loss 100% both directions; carrier stays up"}
    def inject():
        return [sh(n, "tc qdisc replace dev eth1 root netem loss 100%") for n in ("spine1", "leaf1")]
    def restore():
        restore_shaping(["spine1", "leaf1"])
        return [{"node": n, "command": f"{n}-shape-on.sh", "t": time.time(), "rc": 0} for n in ("spine1", "leaf1")]
    return inject, restore, meta


def fault_flap() -> tuple[Callable, Callable, dict]:
    meta = {"link": "spine1:eth1 <-> leaf1:eth1", "how": "down 2 s / up 2 s, 5 cycles (20 s) from T0+5 s",
            "inject_at": 5.0, "restore_at": 25.0}
    holder: dict[str, Any] = {}
    def inject():
        holder["p"] = background(
            "spine1", "sh -c 'for i in 1 2 3 4 5; do ip link set eth1 down; sleep 2; ip link set eth1 up; sleep 2; done'"
        )
        return [{"node": "spine1", "command": "flap loop start", "t": time.time(), "rc": 0}]
    def restore():
        finish("spine1", holder["p"], timeout=40)
        return [sh("spine1", "ip link set eth1 up")]
    return inject, restore, meta


def fault_spine_loss() -> tuple[Callable, Callable, dict]:
    ports = "eth1 eth2 eth3 eth4"
    meta = {"node": "spine1", "how": f"all spine1 fabric links down ({ports}); container keeps running"}
    return (lambda: [sh("spine1", f"sh -c 'for i in {ports}; do ip link set $i down; done'")],
            lambda: [sh("spine1", f"sh -c 'for i in {ports}; do ip link set $i up; done'")], meta)


def fault_leaf_loss() -> tuple[Callable, Callable, dict]:
    ports = "eth1 eth2 eth3 eth4 eth5 eth6 eth7"
    meta = {"node": "leaf1", "how": f"every leaf1 data port down ({ports}): uplinks, host1/host2 rail A, vmhost1, ta1, tb1"}
    return (lambda: [sh("leaf1", f"sh -c 'for i in {ports}; do ip link set $i down; done'")],
            lambda: [sh("leaf1", f"sh -c 'for i in {ports}; do ip link set $i up; done'")], meta)


def fault_degrade(seed: int) -> tuple[Callable, Callable, dict]:
    """1% loss on ONE uplink chosen at random; rate kept at the shaped value."""
    intent = load_intent()
    rate = intent["lab_shaping"]["uplink_rate_mbit"]
    candidates = [("leaf1", "eth1"), ("leaf1", "eth2"), ("leaf2", "eth1"), ("leaf2", "eth2")]
    node, port = random.Random(seed).choice(candidates)
    meta = {"hidden_choice_seed": seed, "candidates": [f"{n}:{p}" for n, p in candidates],
            "how": f"netem loss 1% rate {rate}mbit on one leaf->spine egress; no link down",
            "secret": f"{node}:{port}"}
    def inject():
        return [sh(node, f"tc qdisc replace dev {port} root netem loss 1% rate {rate}mbit limit 1000")]
    def restore():
        restore_shaping([node])
        return [{"node": node, "command": f"{node}-shape-on.sh", "t": time.time(), "rc": 0}]
    return inject, restore, meta


PROMETHEUS = "http://127.0.0.1:9098"
DEGRADE_INJECT = 70.0
DEGRADE_DURATION = 150


def prom_instant(expression: str, at: float) -> list[dict[str, Any]]:
    url = f"{PROMETHEUS}/api/v1/query?" + urllib.parse.urlencode({"query": expression, "time": at})
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.load(response)
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload!r}")
    return payload["data"]["result"]


def by_port(series: list[dict[str, Any]]) -> dict[str, float]:
    return {f"{s['metric']['node']}:{s['metric']['interface']}": float(s["value"][1]) for s in series
            if s["value"][1] not in ("NaN", "+Inf", "-Inf")}


def detect_degraded(t0: float) -> dict[str, Any]:
    """Find the degraded uplink from telemetry only (no access to the secret).

    Baseline = 1-minute rates ending at the injection time; fault = 1-minute
    rates ending 5 s before the run ends. Signals per active leaf uplink:
    (A) root-qdisc drops per MB sent, relative to the leaf's other uplink;
    (B) change in the uplink's share of its leaf's TX bytes.
    """
    drops = 'rate(fabric_qdisc_drops_total{node=~"leaf[1-4]"}[1m]) / (rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]) / 1e6)'
    share = ('rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]) / on (node) group_left '
             'sum by (node) (rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]))')
    tx = 'rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m])'
    retrans = 'rate(fabric_host_tcp_retrans_segments_total[1m]) / rate(fabric_host_tcp_out_segments_total[1m])'
    base_t, fault_t = t0 + DEGRADE_INJECT, t0 + DEGRADE_DURATION - 5
    rows: dict[str, dict[str, float]] = {}
    for label, expr in (("drops_per_mb", drops), ("share", share), ("tx_Bps", tx)):
        for when, tag in ((base_t, "base"), (fault_t, "fault")):
            for port, value in by_port(prom_instant(expr, when)).items():
                rows.setdefault(port, {})[f"{label}_{tag}"] = value
    active = {p: r for p, r in rows.items() if r.get("tx_Bps_fault", 0) > 1e6}
    sibling_ratio = {}
    for port, r in active.items():
        leaf = port.split(":")[0]
        others = [o.get("drops_per_mb_fault", 0) for q, o in active.items() if q.startswith(leaf + ":") and q != port]
        sibling_ratio[port] = r.get("drops_per_mb_fault", 0) / max(max(others, default=0), 1e-9)
    share_drop = {port: r.get("share_fault", 0) - r.get("share_base", 0) for port, r in active.items()}
    suspect_a = max(sibling_ratio, key=sibling_ratio.get) if sibling_ratio else None
    suspect_b = min(share_drop, key=share_drop.get) if share_drop else None
    hosts = {s["metric"]["host"]: float(s["value"][1]) for s in prom_instant(retrans, fault_t)
             if s["value"][1] not in ("NaN", "+Inf", "-Inf")}
    hosts_base = {s["metric"]["host"]: float(s["value"][1]) for s in prom_instant(retrans, base_t)
                  if s["value"][1] not in ("NaN", "+Inf", "-Inf")}
    return {
        "queries": {"drops_per_mb": drops, "share": share, "tx": tx, "host_retrans_ratio": retrans},
        "base_eval_unix": base_t, "fault_eval_unix": fault_t,
        "per_port": rows, "drops_sibling_ratio": sibling_ratio, "share_change": share_drop,
        "suspect_by_drops": suspect_a, "suspect_by_share": suspect_b,
        "host_retrans_ratio_base": hosts_base, "host_retrans_ratio_fault": hosts,
    }


def export_panels(t0: float, out: Path) -> None:
    subprocess.run([
        sys.executable, "-m", "fabric.telemetry.export_panels",
        "--end", str(t0 + DEGRADE_DURATION), "--minutes", str(DEGRADE_DURATION / 60 + 0.5),
        "--step", "10s", "--out", str(out),
    ], check=True, capture_output=True, text=True)


def verify_clean(results: dict[str, Any], after: str) -> None:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "fabric/tests"],
                               cwd=ROOT, capture_output=True, text=True)
    summary = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else completed.stderr[-300:]
    results["verify"].append({"after": after, "command": "python -m pytest -q fabric/tests",
                              "rc": completed.returncode, "summary": summary, "t": time.time()})
    print(json.dumps({"verify_after": after, "rc": completed.returncode, "summary": summary}))


FAULTS = {
    "link-down": fault_link_down,
    "silent-loss": fault_silent_loss,
    "flap": fault_flap,
    "spine-loss": fault_spine_loss,
    "leaf-loss": fault_leaf_loss,
}


# ---- measurement -----------------------------------------------------------------------------

def server_timeline(document: dict[str, Any]) -> dict[str, Any]:
    server = document.get("server_output_json") or {}
    intervals = server.get("intervals", [])
    total = [int(i["sum"]["bytes"]) for i in intervals if "sum" in i]
    streams: dict[int, list[int]] = {}
    for interval in intervals:
        for stream in interval.get("streams", []):
            streams.setdefault(int(stream["socket"]), []).append(int(stream["bytes"]))
    return {"bytes_per_interval": total, "stream_bytes_per_interval": list(streams.values())}


def parse_ping(output: str) -> dict[str, Any]:
    stamps = [float(m.group(1)) for m in re.finditer(r"^\[(\d+\.\d+)\].*bytes from", output, re.M)]
    sent = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", output)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    worst = max(range(len(gaps)), key=lambda i: gaps[i]) if gaps else None
    return {
        "transmitted": int(sent.group(1)) if sent else None,
        "received": int(sent.group(2)) if sent else len(stamps),
        "first_reply": stamps[0] if stamps else None,
        "last_reply": stamps[-1] if stamps else None,
        "max_gap_seconds": gaps[worst] if gaps else None,
        "max_gap_start": stamps[worst] if gaps else None,
    }


def parse_monitor(output: str) -> list[dict[str, Any]]:
    events = []
    for line in output.splitlines():
        m = re.match(r"\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)\]\s*(.*)", line)
        if m:
            # containers print UTC wall-clock time without an offset
            when = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()
            events.append({"t": when, "line": m.group(2)[:200]})
    return events


def converged(intent: dict[str, Any], timeout: float = 180) -> float:
    """Wait until every BGP session is established and every BFD peer is up."""
    started = time.time()
    routers = [n["name"] for n in intent["nodes"]]
    while time.time() - started < timeout:
        ok = True
        for router in routers:
            peers = node_json(router, 'vtysh -c "show bgp summary json"')["ipv4Unicast"]["peers"]
            bfd = node_json(router, 'vtysh -c "show bfd peers json"')
            if any(p.get("state") != "Established" for p in peers.values()) or len(peers) != (4 if router.startswith("spine") else 2):
                ok = False
                break
            if any(p.get("status") != "up" for p in bfd) or len(bfd) != len(peers):
                ok = False
                break
        if ok:
            return time.time() - started
        time.sleep(1)
    raise RuntimeError(f"fabric did not reconverge within {timeout}s")


def bgp_bfd_snapshot() -> dict[str, Any]:
    out = {}
    for node in ("leaf1", "leaf2", "spine1"):
        out[node] = {
            "bfd": node_json(node, 'vtysh -c "show bfd peers json"'),
            "bgp": {k: {"state": v.get("state"), "peerUptimeMsec": v.get("peerUptimeMsec"),
                        "pfxRcd": v.get("pfxRcd")}
                    for k, v in node_json(node, 'vtysh -c "show bgp summary json"')["ipv4Unicast"]["peers"].items()},
        }
    return out


def run_once(intent: dict[str, Any], name: str, fault: tuple[Callable, Callable, dict] | None,
             run_no: int, duration: int = DURATION, rails: tuple[str, ...] = ("A",)) -> dict[str, Any]:
    """One E6 run. `rails`: one ring job per rail, all started at the same T0 (E6 used rail A only)."""
    jobs = []  # (rail, src, dst, src_ip, dst_ip)
    for rail in rails:
        hosts = {h["name"]: h for h in rail_hosts(intent, rail)}
        jobs += [(rail, src, dst, hosts[src]["ip"], hosts[dst]["ip"]) for src, dst in collective_pairs(list(hosts), "ring")]
    links_before = link_snapshot(intent)
    monitors = {m: background(m, f"timeout {duration + 6} ip -ts monitor route nexthop") for m in MONITORS}
    servers = {}
    for index, (_, _, dst, _, _) in enumerate(jobs):
        port = PORT_BASE + (run_no % 40) * 10 + index
        servers[(dst, port)] = background(dst, f"timeout {duration + 25} iperf3 -s -1 -i {INTERVAL} -J -p {port}")
    time.sleep(0.8)
    t0 = time.time() + SYNC_LEAD
    clients = []
    for index, (rail, src, dst, src_ip, dst_ip) in enumerate(jobs):
        port = PORT_BASE + (run_no % 40) * 10 + index
        command = (f"sh {SYNC_SCRIPT} {t0:.6f} timeout {duration + 20} iperf3 -c {dst_ip} "
                   f"-B {src_ip} -p {port} -P {FLOWS} -t {duration} -i {INTERVAL} --get-server-output --json")
        clients.append((rail, src, dst, command, background(src, command)))
    pings = {}
    count = int(duration / 0.1)
    for label, (node, source, target) in PROBES.items():
        bind = f"-I {source} " if source else ""
        pings[label] = background(node, f"ping -D -n -i 0.1 -W 1 -c {count} {bind}{target}")
    events: list[dict[str, Any]] = []
    meta = fault[2] if fault else {}
    if fault:
        inject_at = meta.get("inject_at", INJECT)
        restore_at = meta.get("restore_at", RESTORE)

        def driver() -> None:
            time.sleep(max(0.0, t0 + inject_at - time.time()))
            events.append({"event": "inject", "t": time.time(), "commands": fault[0]()})
            time.sleep(max(0.0, t0 + restore_at - time.time()))
            events.append({"event": "restore", "t": time.time(), "commands": fault[1]()})
        thread = threading.Thread(target=driver)
        thread.start()
    pair_results = []
    for rail, src, dst, command, proc in clients:
        extra = {"rail": rail} if rails != ("A",) else {}
        try:
            parsed = parse_sync(finish(src, proc, timeout=duration + 60))
            document = parsed["iperf3"]
            pair_results.append({
                "source": src, "destination": dst, "command": command, **extra,
                "start_offset": parsed["start"] - t0,
                "received_bytes": document.get("end", {}).get("sum_received", {}).get("bytes"),
                "error": document.get("error"),
                "timeline": server_timeline(document),
            })
        except (RuntimeError, ValueError, json.JSONDecodeError) as error:
            pair_results.append({"source": src, "destination": dst, "command": command, **extra, "error": str(error)[-600:]})
    if fault:
        thread.join()
    for (dst, _), proc in servers.items():
        try:
            finish(dst, proc, timeout=duration + 40)
        except RuntimeError:
            pass
    ping_results = {}
    for label, proc in pings.items():
        node = PROBES[label][0]
        try:
            stdout, _ = proc.communicate(timeout=duration + 30)
            result = json.loads(stdout)[f"clab-{intent['name']}-{node}"][0]
            ping_results[label] = parse_ping(result["stdout"] if isinstance(result["stdout"], str) else "")
        except Exception as error:  # noqa: BLE001 - a failed probe is a result
            ping_results[label] = {"error": str(error)[-300:]}
    monitor_events = {}
    for node, proc in monitors.items():
        try:
            stdout, _ = proc.communicate(timeout=duration + 30)
            out = json.loads(stdout)[f"clab-{intent['name']}-{node}"][0]["stdout"]
            monitor_events[node] = parse_monitor(out if isinstance(out, str) else "")
        except Exception as error:  # noqa: BLE001
            monitor_events[node] = [{"error": str(error)[-300:]}]
    deltas = link_delta(links_before, link_snapshot(intent))
    return {
        "name": name, "run": run_no, "t0": t0, "duration": duration, "interval": INTERVAL,
        "fault": meta, "events": events, "pairs": pair_results, "pings": ping_results,
        "route_monitor": monitor_events, "route_monitor_tz": "utc", "link_deltas": deltas,
        "bgp_bfd_after": bgp_bfd_snapshot(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", nargs="*", default=["all"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--verify", action="store_true", help="run fabric pytest after each fault type")
    args = parser.parse_args()
    refuse_probes()
    intent = load_intent()
    if not shaping.status(intent)["fully_shaped"]:
        raise RuntimeError("E6 runs with the shaped profile; run make fabric-shape-on")
    install_sync([h["name"] for h in rail_hosts(intent, "A")])
    set_routing(intent, "L4", "ring")
    selected = list(FAULTS) + ["degrade"] if args.what == ["all"] else args.what
    if args.what == ["all"]:
        selected = ["baseline"] + selected
    results = json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists() else {
        "label": "EMULATED (veth + Linux forwarding + FRR 10.2.1), SHAPED 500 Mbit/s uplinks",
        "started_at": datetime.now(timezone.utc).isoformat(), "method": __doc__, "runs": [], "verify": [],
    }
    run_no = len(results["runs"])
    try:
        for name in selected:
            for repeat in range(1, args.repeats + 1):
                run_no += 1
                if name == "baseline":
                    fault = None
                elif name == "degrade":
                    fault = fault_degrade(seed=int(time.time()))
                else:
                    fault = FAULTS[name]()
                duration = DEGRADE_DURATION if name == "degrade" else DURATION
                if name == "degrade":
                    fault[2]["inject_at"], fault[2]["restore_at"] = DEGRADE_INJECT, float(duration) + 1
                    secret = fault[2].pop("secret")
                record = run_once(intent, name, fault, run_no, duration)
                if name == "degrade":
                    time.sleep(12)  # let Prometheus scrape the end of the fault window
                    record["detection"] = detect_degraded(record["t0"])
                    panels = ROOT / "fabric" / "telemetry" / f"e6-degrade-panels-r{repeat}.json"
                    export_panels(record["t0"], panels)
                    record["panel_export"] = str(panels.relative_to(ROOT))
                    record["events"].append({"event": "restore", "t": time.time(), "commands": fault[1]()})
                    record["fault"]["secret_revealed_after_detection"] = secret
                    print(json.dumps({"detected_by_drops": record["detection"]["suspect_by_drops"],
                                      "detected_by_share": record["detection"]["suspect_by_share"],
                                      "actual": secret}))
                record["repeat"] = repeat
                record["reconverge_wait_seconds"] = converged(intent)
                results["runs"].append(record)
                RESULT_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
                pings = {k: (v.get("received"), round(v.get("max_gap_seconds") or 0, 2)) for k, v in record["pings"].items()}
                print(json.dumps({"fault": name, "repeat": repeat, "pings(received,max_gap)": pings,
                                  "pair_errors": [p.get("error") for p in record["pairs"] if p.get("error")],
                                  "reconverge_wait": round(record["reconverge_wait_seconds"], 1)}))
            if args.verify:
                verify_clean(results, name)
                RESULT_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    finally:
        set_routing(intent, "L3", "ring")
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        RESULT_PATH.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
