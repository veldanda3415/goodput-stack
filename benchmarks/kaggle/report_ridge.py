"""Tables and the chart for Part A (ridge) and Part B (two instances) from the stage JSONL rows.

    python -m benchmarks.kaggle.report_ridge ridge   benchmarks/results/t4/<run>_ridge
    python -m benchmarks.kaggle.report_ridge twoinst benchmarks/results/t4/<run>_twoinst

Prints markdown tables (pasted into ridge.md / two_instances.md) and, for ridge, writes
charts/ridge_output_vs_max_num_seqs.png: measured offline output tok/s per --max-num-seqs, the HTTP point, the
predicted CALCULATED ceiling (7,000 tok/s) and the predicted measured range (2,000-4,000 tok/s).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CHARTS = Path(__file__).resolve().parents[1] / "results" / "t4" / "charts"


def rows(run: Path, stage: str) -> list[dict]:
    p = run / "results" / stage / f"{stage}.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def f(v, nd=0) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.{nd}f}"
    return str(v)


def ridge(run: Path) -> None:
    rs = rows(run, "ridge")
    off = sorted([r for r in rs if r.get("kind") == "offline" and r["key"].startswith("offline-")], key=lambda r: r["max_num_seqs"])
    print("| max-num-seqs | prompts | output tok/s | total tok/s | req/s | KV pool tokens | preemptions (timed) | running mean | KV usage mean / max | SM clock mean MHz | power mean W | util.gpu mean % | bench CPU % of a core | elapsed s |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in off:
        print(f"| {r['max_num_seqs']} | {r['num_prompts']} | {f(r.get('output_tok_s'), 1)} | {f(r.get('total_tok_s'), 1)} | {f(r.get('req_s'), 2)} | "
              f"{f(r.get('gpu_kv_cache_tokens'))} | {f(r.get('eng_preemptions_delta'))} | {f(r.get('eng_running_mean'), 1)} | "
              f"{f(r.get('eng_kv_usage_mean'), 3)} / {f(r.get('eng_kv_usage_max'), 3)} | {f(r.get('gpu_sm_clock_mhz_mean'))} | "
              f"{f(r.get('gpu_power_w_mean'), 1)} | {f(r.get('gpu_util_gpu_pct_mean'), 1)} | {f(r.get('cpu_bench_pct_mean'))} | "
              f"{f((r.get('bench_json') or {}).get('elapsed_time'), 1)} |")
    mem = [r for r in rs if r.get("kind") == "offline" and r["key"].startswith("memlimit")]
    for r in mem:
        print(f"\nmemlimit {r['key']}: output {f(r.get('output_tok_s'), 1)} tok/s, total {f(r.get('total_tok_s'), 1)}, KV pool "
              f"{f(r.get('gpu_kv_cache_tokens'))}, running mean/max {f(r.get('eng_running_mean'), 1)}/{f(r.get('eng_running_max'))}, "
              f"waiting mean {f(r.get('eng_waiting_mean'), 1)}, KV usage mean/max {f(r.get('eng_kv_usage_mean'), 3)}/{f(r.get('eng_kv_usage_max'), 3)}, "
              f"preemptions timed {f(r.get('eng_preemptions_delta'))} (incl. warm-up {f(r.get('eng_preemptions_total_incl_warmup'))}), "
              f"SM {f(r.get('gpu_sm_clock_mhz_mean'))} MHz, power {f(r.get('gpu_power_w_mean'), 1)} W")
    http = [r for r in rs if r.get("kind") == "http"]
    if http:
        print("\n| run | client procs | requests ok / err | server-counter output tok/s (full window) | harness steady tok/s (sum) | full window s | TTFT p50 / p95 ms | ITL p50 / p95 ms | running mean | waiting mean | util.gpu % | SM MHz | power W | client CPU % of a core | server CPU % of a core | system CPU % (all vCPUs) | max core % |")
        print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in http:
            print(f"| {r['key']} | {r['client_processes']} | {r['requests_ok']} / {r['errors']} | {f(r.get('srv_generation_tokens_per_s'), 1)} | "
                  f"{f(r.get('harness_steady_output_tok_s_sum'), 1)} | {f(r.get('full_window_s'), 1)} | {f(r.get('ttft_ms_p50'))} / {f(r.get('ttft_ms_p95'))} | "
                  f"{f(r.get('itl_ms_p50'), 1)} / {f(r.get('itl_ms_p95'), 1)} | {f(r.get('srv_running_mean'), 1)} | {f(r.get('srv_waiting_mean'), 1)} | "
                  f"{f(r.get('gpu_util_gpu_pct_mean'), 1)} | {f(r.get('gpu_sm_clock_mhz_mean'))} | {f(r.get('gpu_power_w_mean'), 1)} | "
                  f"{f(r.get('cpu_client_pct_mean'))} | {f(r.get('cpu_server_pct_mean'))} | {f(r.get('cpu_sys_pct_mean'), 1)} | {f(r.get('cpu_sys_max_core_pct_mean'), 1)} |")
    for r in rs:
        if r.get("kind") in ("sched_config", "system", "startup", "skipped", "session", "install"):
            keep = {k: v for k, v in r.items() if k in ("key", "usage_context", "max_num_batched_tokens", "max_num_seqs", "max_model_len",
                                                         "enable_chunked_prefill", "vcpus_os", "cpus_physical_psutil", "ram_total_gib",
                                                         "started", "startup_s", "gpu_kv_cache_tokens", "model_weights_gib",
                                                         "max_num_batched_tokens_log", "reason", "session_h", "pip_s", "installer")}
            print("\n", json.dumps(keep))
    if off:
        chart(off, http)


def chart(off: list[dict], http: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    CHARTS.mkdir(parents=True, exist_ok=True)
    x = [r["max_num_seqs"] for r in off if r.get("output_tok_s")]
    y = [r["output_tok_s"] for r in off if r.get("output_tok_s")]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.axhline(7000, color="#b23b3b", ls="--", lw=1)
    ax.text(x[0], 7000, " predicted output ceiling at the ridge, 7,000 tok/s (CALCULATED, datasheet peaks)", va="bottom", fontsize=8, color="#b23b3b")
    ax.axhspan(2000, 4000, color="#e6e6e6", zorder=0)
    ax.text(x[0], 3950, " predicted measured range 2,000–4,000 tok/s", va="top", fontsize=8, color="#555")
    ax.plot(x, y, "o-", color="#3b6ea5", label="offline, vllm bench throughput (measured)")
    for xi, yi in zip(x, y):
        ax.annotate(f"{yi:,.0f}", (xi, yi), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8)
    for r in http:
        v = r.get("srv_generation_tokens_per_s")
        if v:
            ax.plot([r["users"]], [v], "s", color="#d08c2c", label=f"HTTP, {r['users']} users, {r['client_processes']} client proc (measured)")
            ax.annotate(f"{v:,.0f}", (r["users"], v), textcoords="offset points", xytext=(10, -12), fontsize=8, color="#d08c2c")
    ax.set_xlabel("--max-num-seqs (offline) / concurrent users (HTTP)")
    ax.set_ylabel("output tokens / s")
    ax.set_title("Qwen2.5-3B-Instruct FP16 on one T4, prompt 128 / output 256 — Kaggle T4, real", fontsize=10)
    ax.set_ylim(0, 7600)
    ax.set_xticks(x)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=8, frameon=False, loc="center right")
    fig.tight_layout()
    out = CHARTS / "ridge_output_vs_max_num_seqs.png"
    fig.savefig(out, dpi=130)
    print(f"\nchart -> {out}")


def twoinst(run: Path) -> None:
    rs = rows(run, "twoinst")
    st = {r["key"]: r for r in rs if r.get("kind") == "startup"}
    for k, r in st.items():
        print(json.dumps({x: r.get(x) for x in ("key", "util", "started", "startup_s", "model_weights_gib", "available_kv_gib",
                                                  "gpu_kv_cache_tokens", "exit_code", "compute_apps", "error_lines", "model", "model_revision")})[:3000])
    print("\n| condition | instance | users | output tok/s (server counters, joint window) | harness steady tok/s | TTFT p50 / p95 ms | ITL p50 / p95 ms | running mean | waiting mean | KV usage mean |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rs:
        if r.get("kind") != "condition":
            continue
        for n in ("i1", "i2"):
            per = r.get(f"inst_{n}")
            joint = r.get(f"joint_{n}") or {}
            if per is None and not joint:
                continue
            per = per or {}
            print(f"| {r['key']} | {n} | {per.get('users', 0)} | {f(joint.get('srv_generation_tokens_per_s'), 1)} | "
                  f"{f(per.get('harness_steady_output_tok_s'), 1)} | {f(per.get('ttft_ms_p50'))} / {f(per.get('ttft_ms_p95'))} | "
                  f"{f(per.get('itl_ms_p50'), 1)} / {f(per.get('itl_ms_p95'), 1)} | {f(joint.get('srv_running_mean'), 1)} | "
                  f"{f(joint.get('srv_waiting_mean'), 1)} | {f(joint.get('srv_kv_usage_mean'), 3)} |")
    print("\n| condition | combined output tok/s (server counters) | combined harness steady tok/s | joint window s | util.gpu % | SM MHz | power W | mem used MiB | compute apps (mid-run) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rs:
        if r.get("kind") == "condition":
            apps = "; ".join(f"{a['pid']} {a['process'].split('/')[-1]} {a['used_memory']}" for a in r.get("compute_apps_mid_run") or []) or "none listed"
            print(f"| {r['key']} | {f(r.get('combined_output_tok_s_server_counters'), 1)} | {f(r.get('combined_harness_steady_output_tok_s'), 1)} | "
                  f"{f(r.get('joint_window_s'), 1)} | {f(r.get('gpu_util_gpu_pct_mean'), 1)} | {f(r.get('gpu_sm_clock_mhz_mean'))} | "
                  f"{f(r.get('gpu_power_w_mean'), 1)} | {f(r.get('gpu_mem_used_mib_mean'))} | {apps} |")
    for r in rs:
        if r.get("kind") in ("mps", "skipped", "session", "install", "system", "abort"):
            print("\n", json.dumps({k: v for k, v in r.items() if k not in ("env", "timestamp_utc", "git_sha", "run_id", "gpu", "driver",
                                                                            "cuda_driver", "label", "torch", "flag_source")})[:2500])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", choices=["ridge", "twoinst"])
    ap.add_argument("run", type=Path)
    a = ap.parse_args()
    (ridge if a.part == "ridge" else twoinst)(a.run)


if __name__ == "__main__":
    main()
