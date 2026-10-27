"""E8 §8: per-run flow placement vs step cost for the fixed 1 % loss uplink (e8-degrade-results.json).

Per leaf1-sourced pair: flows on the lossy uplink (eth1) vs eth2, their mean
throughput and retransmits from `ss -tin` (bytes_acked / retrans deltas
T0+15 -> T0+25 s), pair rate before/during the fault, leaf1 uplink rates.

Usage: python -m fabric.experiments.e8_degrade_report
"""
from __future__ import annotations

import json
import re
import statistics

from fabric.experiments import e6_report
from fabric.experiments.e8 import DEGRADE_PATH, flap_summary

A, B = 15.0, 25.0  # fault-window slice (fault from T0+10 s)


def ss_samples(text: str) -> list[tuple[float, dict[tuple[str, int], dict[str, int]]]]:
    out, cur, key = [], None, None
    for line in text.splitlines():
        if line.startswith("T "):
            cur = (float(line.split()[1]), {})
            out.append(cur)
            continue
        m = re.search(r"(\d+\.\d+\.\d+\.\d+):(\d+)\s+(\d+\.\d+\.\d+\.\d+):(\d+)", line)
        if m and cur is not None:
            key = (m.group(3), int(m.group(2)))  # (dst ip, local sport)
            continue
        if key and cur is not None and "bytes_acked" in line:
            acked = re.search(r"bytes_acked:(\d+)", line)
            retr = re.search(r"retrans:\d+/(\d+)", line)
            cur[1][key] = {"acked": int(acked.group(1)), "retrans": int(retr.group(1)) if retr else 0}
            key = None
    return out


def at(samples, t: float):
    best = None
    for ts, flows in samples:
        if ts <= t:
            best = flows
    return best or {}


def main() -> None:
    runs = json.loads(DEGRADE_PATH.read_text())["runs"]
    print("| run | step s (Δ vs 20.0) | pair | flows on eth1 / eth2 | pair Mbit/s T0+2–10 → T0+15–25 | "
          "mean Mbit/s per flow eth1 / eth2 | retrans per flow eth1 / eth2 | lossy leaf eth1 / eth2 tx Mbit/s T0+15–25 |")
    print("|---|---|---|---|---|---|---|---|")
    for run in runs:
        t0 = run["t0"]
        step = flap_summary(run)["step"]
        rows = []
        for p in run["pairs"]:
            if p["source"] not in run.get("senders", ["host1", "host2"]):
                continue
            pts = e6_report.cumulative(p)
            rate = lambda a, b: (e6_report.bytes_at(pts, b) - e6_report.bytes_at(pts, a)) * 8 / (b - a) / 1e6
            flows = run["placement"][p["source"]]["flows"]
            dev = {f["sport"]: f.get("dev") for f in flows}
            samples = ss_samples(run["samplers"][f"ss:{p['source']}"])
            s1, s2 = at(samples, t0 + A), at(samples, t0 + B)
            per = {"eth1": [], "eth2": []}
            for (dst, sport), v in s2.items():
                if sport in dev and dev[sport] in per and (dst, sport) in s1:
                    d_acked = (v["acked"] - s1[(dst, sport)]["acked"]) * 8 / (B - A) / 1e6
                    d_retr = v["retrans"] - s1[(dst, sport)]["retrans"]
                    if d_acked > 0.01 or d_retr:  # skip iperf3's idle control connection
                        per[dev[sport]].append((d_acked, d_retr))
            n1, n2 = len(per["eth1"]), len(per["eth2"])
            m = lambda xs, i: f"{statistics.mean(x[i] for x in xs):.1f}" if xs else "—"
            rows.append((p["source"], p["destination"], n1, n2, rate(2, 10), rate(A, B),
                         m(per["eth1"], 0), m(per["eth2"], 0), m(per["eth1"], 1), m(per["eth2"], 1)))
        up = []
        leaf = run.get("lossy", "leaf1:eth1").split(":")[0]
        for line in run["samplers"][f"uplinks:{leaf}"].splitlines():
            q = line.split()
            if len(q) == 5 and "nan" not in q:
                up.append([float(q[0])] + [int(x) for x in q[1:]])
        sel = [u for u in up if t0 + A <= u[0] <= t0 + B]
        tx = lambda c: (sel[-1][c] - sel[0][c]) * 8 / (sel[-1][0] - sel[0][0]) / 1e6
        for i, r in enumerate(rows):
            lead = f"| {run['run']} {run.get('lossy', 'leaf1:eth1')} | {step:.2f} (+{step - 20.0:.2f}) " if i == 0 else "| | "
            tail = f"{tx(1):.0f} / {tx(3):.0f}" if i == 0 else ""
            print(f"{lead}| {r[0]}→{r[1]} | {r[2]} / {r[3]} | {r[4]:.0f} → {r[5]:.0f} | {r[6]} / {r[7]} | {r[8]} / {r[9]} | {tail} |")


if __name__ == "__main__":
    main()
