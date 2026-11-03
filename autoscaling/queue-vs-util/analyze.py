#!/usr/bin/env python3
"""Build 17 Task A analysis: per-cycle and per config x profile metrics of the queue-vs-util cycles + charts.

    .venv/bin/python autoscaling/queue-vs-util/analyze.py [--order autoscaling/results/queue-vs-util/order.jsonl]

Per cycle, from the loadgen run dir (log.jsonl events, samples.jsonl at ~1 Hz, requests.jsonl):
  TTFT p50 / p95 / max of ok requests sent in the load phase, and of those sent in the first 60 s after load start;
  ITL p50 = median over requests of each request's own ITL p50; requests ok / failed;
  load start -> first scale-up decision (HPA desiredReplicas rises) -> first new pod Ready -> first new pod serving;
  replica-seconds = integral of the Deployment's spec.replicas over a fixed window [load start, load start + 330 s]
  (150 s load + 180 s, long enough for 3 -> 1 at 60 s stabilization and -1 pod / 30 s; after run_end the value is held);
  scale-down: load stop -> first scale-down decision, load stop -> back at 1 replica;
  pod CPU (cores, sum over pods, cgroup), node CPU busy share, queue (direct per-pod scrape sum) during the load.
Writes analysis.json, cycles.md (per-cycle table), summary.md (median and range per config x profile) and charts.
"""
import argparse, json, pathlib, statistics

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "autoscaling" / "results" / "queue-vs-util"
WINDOW_S = 330.0
COLORS = {"keda": "#3b6ea5", "cpu50": "#c8553d", "cpu80": "#e0a458"}


def pct(xs, p):
    if not xs:
        return None
    s = sorted(xs); k = (len(s) - 1) * p / 100; f = int(k)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f)


def jl(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def cycle(row):
    d = pathlib.Path(row["run_dir"])
    log, samples, reqs = jl(d / "log.jsonl"), jl(d / "samples.jsonl"), jl(d / "requests.jsonl")
    ev = lambda name: [e for e in log if e["event"] == name]
    ls, lstop, end = ev("load_start")[0]["rel_s"], ev("load_stop")[0]["rel_s"], ev("run_end")[0]["rel_s"]
    up = [e for e in ev("hpa_desired_change") if e["rel_s"] >= ls and (e["new"] or 0) > (e["old"] or 0)]
    down = [e for e in ev("hpa_desired_change") if e["rel_s"] >= ls and (e["new"] or 0) < (e["old"] or 0)]
    ready = [e for e in ev("pod_ready") if e["rel_s"] >= ls]
    served = [e for e in ev("pod_first_served") if e["rel_s"] >= ls]
    ok = [r for r in reqs if r.get("ok") and r.get("ttft_ms") is not None]
    first = [r["ttft_ms"] for r in ok if ls <= r["send_rel_s"] < ls + 60]
    tt = [r["ttft_ms"] for r in ok]
    itl = [r["itl_p50_ms"] for r in ok if r.get("itl_p50_ms") is not None]
    # replica-seconds over the fixed window, spec replicas (pods the autoscaler asked for = what is paid for)
    ss = sorted(samples, key=lambda s: s["rel_s"])
    t_a, t_b, rs = ls, ls + WINDOW_S, 0.0
    pts = [(s["rel_s"], s["spec"]) for s in ss if s.get("spec") is not None]
    for (t0, v), (t1, _) in zip(pts, pts[1:] + [(max(t_b, pts[-1][0]), pts[-1][1])]):
        lo, hi = max(t0, t_a), min(t1, t_b)
        if hi > lo:
            rs += v * (hi - lo)
    if pts and pts[-1][0] < t_b:   # held value after run_end already counted by the sentinel above
        pass
    load = [s for s in ss if ls <= s["rel_s"] <= lstop]
    back1 = next((s["rel_s"] for s in ss if s["rel_s"] > lstop and s.get("spec") == 1 and s.get("ready") == 1
                  and all(x.get("spec") == 1 for x in ss if x["rel_s"] >= s["rel_s"])), None)
    mean = lambda xs: round(statistics.fmean(xs), 3) if xs else None
    r = lambda x, n=1: None if x is None else round(x, n)
    return {
        "index": row["index"], "config": row["config"], "profile": row["profile"], "run_dir": str(d.relative_to(REPO)),
        "start": row["start"],
        "requests_ok": len([q for q in reqs if q.get("ok")]), "requests_failed": len([q for q in reqs if not q.get("ok")]),
        "ttft_p50_ms": r(pct(tt, 50)), "ttft_p95_ms": r(pct(tt, 95)), "ttft_max_ms": r(max(tt) if tt else None),
        "ttft60_p50_ms": r(pct(first, 50)), "ttft60_p95_ms": r(pct(first, 95)), "ttft60_max_ms": r(max(first) if first else None),
        "itl_p50_ms": r(statistics.median(itl) if itl else None, 2),
        "scale_up_decision_s": r(up[0]["rel_s"] - ls) if up else None,
        "scale_up_to": up[0]["new"] if up else None,
        "first_new_pod_ready_s": r(ready[0]["rel_s"] - ls) if ready else None,
        "first_new_pod_serving_s": r(served[0]["rel_s"] - ls) if served else None,
        "max_replicas": max((s["spec"] or 0) for s in ss if s["rel_s"] >= ls) if ss else None,
        "reached_max_replicas_s": r(next((x["rel_s"] - ls for x in ss if x["rel_s"] >= ls and x["spec"] == max(
            (y["spec"] or 0) for y in ss if y["rel_s"] >= ls)), None)) if any(x["spec"] and x["spec"] > 1 for x in ss) else None,
        "first_up_hpa_reading": (lambda m: None if not m else (m[0].get("resource") or m[0].get("external"))["current"])(
            up[0].get("hpa_metric")) if up else None,
        "replica_seconds": r(rs),
        "scale_down_decision_after_stop_s": r(next((e["rel_s"] - lstop for e in down if e["rel_s"] >= lstop), None)),
        "scale_down_during_load": sum(1 for e in down if e["rel_s"] < lstop),
        "back_to_1_after_stop_s": r(back1 - lstop) if back1 is not None else None,
        "load_s": r(lstop - ls), "run_end_after_stop_s": r(end - lstop),
        "pod_cpu_cores_mean_load": mean([s["pod_cpu_cores"] for s in load if s.get("pod_cpu_cores") is not None]),
        "node_cpu_busy_mean_load": mean([s["node_cpu_busy"] for s in load if s.get("node_cpu_busy") is not None]),
        "queue_mean_load": mean([s["queue"] for s in load]), "queue_max_load": max((s["queue"] for s in load), default=None),
        "hpa_up_metric": up[0].get("hpa_metric") if up else None,
    }


def series(c):
    d = REPO / c["run_dir"]
    log, samples, reqs = jl(d / "log.jsonl"), jl(d / "samples.jsonl"), jl(d / "requests.jsonl")
    ls = next(e["rel_s"] for e in log if e["event"] == "load_start")
    return ([(s["rel_s"] - ls, s["spec"], s.get("pod_cpu_cores"), s["queue"]) for s in samples],
            [(q["send_rel_s"] - ls, q["ttft_ms"]) for q in reqs if q.get("ok") and q.get("ttft_ms") is not None])


def charts(cycles, groups):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    profs = [p for p in ("heavy", "light") if any(c["profile"] == p for c in cycles)]
    cfgs = [c for c in COLORS if any(x["config"] == c for x in cycles)]
    fig, axes = plt.subplots(len(profs), len(cfgs), figsize=(4.2 * len(cfgs), 3.4 * len(profs)), squeeze=False, sharex=True)
    for i, p in enumerate(profs):
        for j, cfg in enumerate(cfgs):
            ax = axes[i][j]
            cs = sorted([c for c in cycles if c["config"] == cfg and c["profile"] == p], key=lambda c: c["replica_seconds"])
            if not cs:
                ax.set_axis_off(); continue
            rep = cs[len(cs) // 2]   # median replica-seconds cycle
            smp, tt = series(rep)
            ax.scatter([t for t, _ in tt], [v / 1000 for _, v in tt], s=6, color="#888888", label="TTFT (s), per request")
            ax.set_ylabel("TTFT s" if j == 0 else "")
            ax2 = ax.twinx()
            ax2.step([t for t, *_ in smp], [s for _, s, *_ in smp], where="post", color=COLORS[cfg], lw=2, label="replicas (spec)")
            ax2.set_ylim(0, 3.5); ax2.set_yticks([1, 2, 3])
            ax.axvspan(0, 150, color="#f0f0f0", zorder=-1)
            ax.set_title(f"{cfg}, {p} (cycle #{rep['index']}, {rep['replica_seconds']:.0f} replica-s)", fontsize=9)
            ax.set_xlim(-20, 330)
            if i == len(profs) - 1:
                ax.set_xlabel("s from load start (grey = load)")
    fig.suptitle("llamacpp-pool, real CPU (laptop): replicas and client TTFT, representative cycle per config", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "replicas_ttft_timeline.png", dpi=120)
    fig, axs = plt.subplots(1, 2, figsize=(10, 4))
    for ax, key, lab in ((axs[0], "ttft_p50_ms", "p50"), (axs[1], "ttft_p95_ms", "p95")):
        for c in cycles:
            ax.scatter(c["replica_seconds"], c[key] / 1000, color=COLORS[c["config"]],
                       marker="o" if c["profile"] == "heavy" else "^", s=40)
        ax.set_xlabel(f"replica-seconds in {WINDOW_S:.0f} s from load start")
        ax.set_ylabel(f"client TTFT {lab}, s (whole load phase)")
        ax.set_ylim(0, None)
        ax.spines[["top", "right"]].set_visible(False)
    for cfg in cfgs:
        axs[0].scatter([], [], color=COLORS[cfg], label=cfg)
    axs[0].scatter([], [], color="k", marker="o", label="heavy (6 streams)"); axs[0].scatter([], [], color="k", marker="^", label="light (2 streams)")
    axs[0].legend(fontsize=7, frameon=False)
    fig.suptitle("TTFT vs replica-seconds, every cycle (llamacpp-pool, real CPU (laptop))", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "ttft_vs_replica_seconds.png", dpi=120)


METRICS = [("ttft_p50_ms", "TTFT p50 ms"), ("ttft_p95_ms", "TTFT p95 ms"), ("ttft_max_ms", "TTFT max ms"),
           ("ttft60_p50_ms", "TTFT p50 first 60 s"), ("ttft60_p95_ms", "TTFT p95 first 60 s"), ("ttft60_max_ms", "TTFT max first 60 s"),
           ("itl_p50_ms", "ITL p50 ms"), ("requests_ok", "ok"), ("requests_failed", "failed"),
           ("scale_up_decision_s", "load → scale-up decision s"), ("first_new_pod_ready_s", "→ new pod Ready s"),
           ("first_new_pod_serving_s", "→ new pod serving s"), ("max_replicas", "max replicas"), ("reached_max_replicas_s", "load → max replicas (spec) s"),
           ("replica_seconds", "replica-s (330 s)"), ("scale_down_decision_after_stop_s", "stop → scale-down decision s"),
           ("back_to_1_after_stop_s", "stop → back at 1 s"), ("pod_cpu_cores_mean_load", "pod CPU cores (load mean)"),
           ("node_cpu_busy_mean_load", "node CPU busy (load mean)"), ("queue_mean_load", "queue mean (load)"),
           ("queue_max_load", "queue max (load)")]


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float) and abs(v) < 10 and v != int(v):
        return f"{v:.2f}"
    return f"{v:,.0f}"


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--order", type=pathlib.Path, default=REPO / "autoscaling" / "results" / "queue-vs-util" / "order.jsonl")
    ap.add_argument("--out", type=pathlib.Path, default=REPO / "autoscaling" / "results" / "queue-vs-util", help="where analysis.json, *.md and charts go")
    a = ap.parse_args()
    OUT = a.out
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [r for r in jl(a.order) if r.get("rc") == 0 and r.get("run_dir")]
    for r in rows:   # run dirs moved after the run (runs-fixed-prompts/): find them by name next to the order file
        if not pathlib.Path(r["run_dir"]).exists():
            r["run_dir"] = str(next(a.order.resolve().parent.glob(f"runs*/{pathlib.Path(r['run_dir']).name}")))
    cycles = [cycle(r) for r in rows]
    groups = {}
    for c in cycles:
        groups.setdefault((c["config"], c["profile"]), []).append(c)
    summ = {}
    for (cfg, prof), cs in sorted(groups.items()):
        s = {"n": len(cs)}
        for k, _ in METRICS:
            vals = [c[k] for c in cs if c[k] is not None]
            s[k] = {"median": statistics.median(vals) if vals else None, "min": min(vals) if vals else None,
                    "max": max(vals) if vals else None, "n": len(vals)}
        summ[f"{cfg}:{prof}"] = s
    (OUT / "analysis.json").write_text(json.dumps({"window_s": WINDOW_S, "cycles": cycles, "summary": summ}, indent=1) + "\n")
    lines = ["| metric | " + " | ".join(summ) + " |", "|---|" + "---:|" * len(summ)]
    lines.append("| cycles | " + " | ".join(str(s["n"]) for s in summ.values()) + " |")
    for k, label in METRICS:
        cells = []
        for s in summ.values():
            m = s[k]
            cells.append("—" if m["median"] is None else
                         f"{fmt(m['median'])} ({fmt(m['min'])}–{fmt(m['max'])})" + (f" [n={m['n']}]" if m["n"] != s["n"] else ""))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    keys = ["index", "config", "profile"] + [k for k, _ in METRICS]
    cl = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    cl += ["| " + " | ".join(fmt(c[k]) if not isinstance(c[k], str) else c[k] for k in keys) + " |" for c in sorted(cycles, key=lambda c: c["index"])]
    (OUT / "cycles.md").write_text("\n".join(cl) + "\n")
    if cycles:
        charts(cycles, groups)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
