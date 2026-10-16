"""Summarize e6-results.json (EMULATED, shaped) into the E6 tables.

Step time: the time at which the slowest ring pair has received W bytes,
where W = mean over baseline runs of the slowest pair's bytes at T0+20 s.
Pair timelines are 0.5 s receiver (server) intervals offset by each client's
synchronized start. Loss window per probe: longest reply gap minus the 0.1 s
probe interval. Stream stall: longest run of zero-byte 0.5 s intervals of any
stream. FIB reaction: first `ip monitor route nexthop` event on the named
leaf after inject / last event after restore.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fabric.experiments.e6_drills import INTERVAL, RESULT_PATH

STEP_REFERENCE = 20.0


def cumulative(pair: dict[str, Any]) -> list[tuple[float, float]]:
    start = pair.get("start_offset", 0.0)
    points, total = [(start, 0.0)], 0.0
    for index, size in enumerate(pair["timeline"]["bytes_per_interval"]):
        total += size
        points.append((start + (index + 1) * INTERVAL, total))
    return points


def bytes_at(points: list[tuple[float, float]], t: float) -> float:
    for (t1, b1), (t2, b2) in zip(points, points[1:]):
        if t1 <= t <= t2:
            return b1 + (b2 - b1) * (t - t1) / (t2 - t1)
    return points[-1][1] if t > points[-1][0] else 0.0


def time_to(points: list[tuple[float, float]], target: float) -> float | None:
    for (t1, b1), (t2, b2) in zip(points, points[1:]):
        if b2 >= target:
            return t1 + (t2 - t1) * (target - b1) / (b2 - b1) if b2 > b1 else t2
    return None


def step_time(run: dict[str, Any], target: float) -> float | None:
    times = []
    for pair in run["pairs"]:
        if "timeline" not in pair:
            return None
        t = time_to(cumulative(pair), target)
        if t is None:
            return None
        times.append(t)
    return max(times)


def stream_stall(run: dict[str, Any]) -> tuple[float, int, int]:
    """(longest zero-throughput run in s, streams stalled >= 1 s, total streams)."""
    longest, stalled, total = 0, 0, 0
    for pair in run["pairs"]:
        for stream in pair.get("timeline", {}).get("stream_bytes_per_interval", []):
            total += 1
            run_len = best = 0
            for size in stream[1:-1]:  # skip ramp-up / tail intervals
                run_len = run_len + 1 if size == 0 else 0
                best = max(best, run_len)
            longest = max(longest, best)
            stalled += best * INTERVAL >= 1.0
    return longest * INTERVAL, stalled, total


def fault_window_rate(run: dict[str, Any]) -> dict[str, float]:
    """Per-pair mean receive rate (Mbit/s) inside the fault window."""
    inject = run["fault"].get("inject_at", 10.0)
    restore = min(run["fault"].get("restore_at", 20.0), run["duration"])
    out = {}
    for pair in run["pairs"]:
        if "timeline" not in pair:
            continue
        pts = cumulative(pair)
        out[f"{pair['source']}->{pair['destination']}"] = (
            (bytes_at(pts, restore) - bytes_at(pts, inject)) * 8 / (restore - inject) / 1e6
        )
    return out


def degrade_impact(run: dict[str, Any], target: float) -> dict[str, Any]:
    """Pre-fault [T0+10, inject] vs fault [inject+10, end-5] per-pair rates, and the
    step time those rates imply for W bytes at the slowest pair (same run)."""
    inject, end = run["fault"]["inject_at"], run["duration"]
    pre, fault = {}, {}
    for pair in run["pairs"]:
        pts = cumulative(pair)
        name = f"{pair['source']}->{pair['destination']}"
        pre[name] = (bytes_at(pts, inject) - bytes_at(pts, 10.0)) / (inject - 10.0)
        fault[name] = (bytes_at(pts, end - 5) - bytes_at(pts, inject + 10)) / (end - 15 - inject)
    step_pre, step_fault = target / min(pre.values()), target / min(fault.values())
    return {
        "pre_mbps": {k: v * 8 / 1e6 for k, v in pre.items()},
        "fault_mbps": {k: v * 8 / 1e6 for k, v in fault.items()},
        "step_pre": step_pre, "step_fault": step_fault, "step_increase_pct": 100 * (step_fault / step_pre - 1),
    }


def fib_reaction(run: dict[str, Any], node: str) -> tuple[float | None, float | None, int]:
    # Records written before the UTC fix parsed the containers' UTC stamps as
    # local time; shift them by the local UTC offset at T0.
    shift = 0.0 if run.get("route_monitor_tz") == "utc" else time.localtime(run["t0"]).tm_gmtoff
    events = [{**e, "t": e["t"] + shift} for e in run["route_monitor"].get(node, []) if "t" in e]
    inject = next((e["t"] for e in run["events"] if e["event"] == "inject"), None)
    restore = next((e["t"] for e in run["events"] if e["event"] == "restore"), None)
    first = next((e["t"] - inject for e in events if inject and e["t"] >= inject - 0.05), None)
    after = [e["t"] - restore for e in events if restore and e["t"] >= restore - 0.05]
    return first, (max(after) if after else None), len(events)


def probe_summary(run: dict[str, Any]) -> dict[str, str]:
    out = {}
    for label, ping in run["pings"].items():
        if "error" in ping:
            out[label] = "probe error"
            continue
        lost = (ping["transmitted"] or 0) - (ping["received"] or 0)
        gap = max(0.0, (ping["max_gap_seconds"] or 0) - 0.1)
        at = (ping["max_gap_start"] or run["t0"]) - run["t0"]
        out[label] = "ok" if lost == 0 and gap < 0.2 else f"lost {lost}, gap {gap:.2f}s at T0+{at:.1f}"
    return out


def summarize(path: Path = RESULT_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text())
    runs = data["runs"]
    baseline = [r for r in runs if r["name"] == "baseline"]
    target = statistics.mean(
        min(bytes_at(cumulative(p), STEP_REFERENCE) for p in r["pairs"]) for r in baseline
    )
    base_step = statistics.mean(step_time(r, target) for r in baseline)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        groups[run["name"]].append(run)
    table = []
    for name, items in groups.items():
        rows = []
        for run in items:
            first, last, count = fib_reaction(run, "leaf2" if name == "leaf-loss" else "leaf1")
            stall, stalled, streams = stream_stall(run)
            step = step_time(run, target)
            reached = min(cumulative(p)[-1][1] for p in run["pairs"] if "timeline" in p) / target
            rows.append({
                "reached_fraction_of_W": reached,
                "repeat": run["repeat"], "step": step,
                "step_delta": None if step is None else step - base_step,
                "fib_first_after_inject": first, "fib_last_after_restore": last, "fib_events": count,
                "stall_s": stall, "streams_stalled_1s": stalled, "streams": streams,
                "fault_rate_mbps": fault_window_rate(run) if name != "baseline" else {},
                "probes": probe_summary(run),
                "reconverge_wait": run.get("reconverge_wait_seconds"),
                "detection": run.get("detection"),
                "degrade_impact": degrade_impact(run, target) if name == "degrade" else None,
                "secret": run["fault"].get("secret_revealed_after_detection"),
            })
        table.append({"name": name, "fault": items[0]["fault"], "runs": rows})
    return {"target_bytes": target, "baseline_step": base_step, "faults": table, "verify": data.get("verify", [])}


def fmt(values: list[float | None], digits: int = 2) -> str:
    return " / ".join("—" if v is None else f"{v:.{digits}f}" for v in values)


def fmt_step(rows: list[dict[str, Any]]) -> str:
    return " / ".join(
        f"{r['step']:.2f}" if r["step"] is not None else f">30 ({100 * r['reached_fraction_of_W']:.0f}% of W)"
        for r in rows
    )


def main() -> None:
    s = summarize()
    print(f"W = {s['target_bytes']/1e9:.3f} GB; baseline step {s['baseline_step']:.2f} s")
    print("| Fault | Step time s (r1/r2/r3) | Δ vs baseline s | Longest stream stall s | Streams stalled ≥1 s | FIB first change after inject s | Last FIB change after restore s | Wait to all-up after run s |")
    print("|---|---|---|---|---|---|---|---|")
    for f in s["faults"]:
        r = f["runs"]
        print(f"| {f['name']} | {fmt_step(r)} | {fmt([x['step_delta'] for x in r])} | "
              f"{fmt([x['stall_s'] for x in r], 1)} | {' / '.join(str(x['streams_stalled_1s']) + '/' + str(x['streams']) for x in r)} | "
              f"{fmt([x['fib_first_after_inject'] for x in r], 3)} | {fmt([x['fib_last_after_restore'] for x in r], 2)} | "
              f"{fmt([x['reconverge_wait'] for x in r], 1)} |")
    print()
    for f in s["faults"]:
        if f["name"] == "baseline":
            continue
        print(f["name"], "fault-window Mbit/s per pair:",
              [{k: round(v) for k, v in x["fault_rate_mbps"].items()} for x in f["runs"]])
        print("   probes:", [x["probes"] for x in f["runs"]][0])
        for x in f["runs"]:
            if x["detection"]:
                print("   detection:", x["detection"]["suspect_by_drops"], x["detection"]["suspect_by_share"], "actual", x["secret"])
            if x["degrade_impact"]:
                d = x["degrade_impact"]
                print(f"   impact: step-equivalent {d['step_pre']:.2f} s -> {d['step_fault']:.2f} s ({d['step_increase_pct']:+.1f}%);",
                      "pre", {k: round(v) for k, v in d["pre_mbps"].items()}, "fault", {k: round(v) for k, v in d["fault_mbps"].items()})
    print("verify:", [(v["after"], v["summary"]) for v in s["verify"]])


if __name__ == "__main__":
    main()
