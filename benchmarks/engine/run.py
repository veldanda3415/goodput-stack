"""Engine benchmark runner: for each sweep point, start a fresh llama-server,
drive load DIRECTLY against it (no router), collect metrics, stop it, write results.

    python -m benchmarks.engine.run ttft
    python -m benchmarks.engine.run slot_limit --set client.requests=8 --set server.threads=4
    python -m benchmarks.engine.run ttft --dry-run         # show points + server commands
    python -m benchmarks.engine.run --list
    python -m benchmarks.engine.run --prune ttft          # prune raw files only
"""

from __future__ import annotations

import argparse
import asyncio
import shlex
import sys
import traceback
from pathlib import Path

from ..harness import client, config, stats, storage, sysinfo
from . import bench
from .server import LlamaServer, build_args, probe_memory

DEFAULT_CONFIG = Path(__file__).resolve().parent / "configs" / "llamacpp.yaml"

TABLE_COLS = [
    "status", "requests_ok", "ttft_ms_p50", "ttft_ms_p95", "srv_prompt_ms_p50", "itl_ms_p50",
    "e2e_ms_p50", "agg_output_tok_s", "kv_buffer_mib", "rss_peak_mib", "m_deferred_max",
    "m_gauge_pred_tok_s_mean_nonzero", "m_counter_per_slot_tok_s", "m_counter_wall_tok_s",
    "m_gauge_zero_windows", "gen_tok_s", "effective_bw_gb_s",
]


def run_server_point(cfg: dict, point_dir: Path) -> dict:
    probe = probe_memory(cfg, point_dir) if cfg["server"].get("probe_memory") else {}
    with LlamaServer(cfg, point_dir) as srv:
        result = asyncio.run(client.run_point(srv.base_url, cfg))
    storage.write_jsonl(point_dir / "requests.jsonl", result["records"])
    storage.write_jsonl(point_dir / "metrics.jsonl", result["samples"] + [{"idle_probe": result["idle_probe"]}])
    row = stats.summarize_load(result)
    mem = srv.memory_info()
    row |= {k: v for k, v in mem.items() if k != "log_memory_lines"}
    return row | probe | {"_memory_lines": mem["log_memory_lines"]}


def run_bench_point(cfg: dict, point_dir: Path) -> dict:
    rows = bench.run_llama_bench(cfg)
    storage.write_jsonl(point_dir / "bench.jsonl", rows)
    return bench.summarize_bench(rows)


def print_table(rows: list[dict], param_keys: list[str]) -> None:
    cols = [k.split(".")[-1] for k in param_keys] + [c for c in TABLE_COLS if any(r.get(c) is not None for r in rows)]
    cells = [[str(r.get(c, "")) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    print("  ".join(c.rjust(w) for c, w in zip(cols, widths)))
    for row in cells:
        print("  ".join(v.rjust(w) for v, w in zip(row, widths)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment", nargs="?")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="mark this run so retention never prunes it")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--prune", action="store_true", help="only prune raw files of old runs")
    args = ap.parse_args(argv)

    doc = config.load(args.config)
    if args.list or not args.experiment:
        for name, exp in doc["experiments"].items():
            print(f"{name:20s} {' '.join((exp.get('description') or '').split())}")
        return 0

    cfg, sweep = config.resolve(doc, args.experiment, args.overrides)
    points = config.expand(cfg, sweep)
    st = cfg["storage"]
    results_dir = Path(st["results_dir"])

    if args.prune:
        for run in storage.prune(results_dir, args.experiment, st["keep_raw_runs"]):
            print(f"pruned raw files: {run}")
        return 0

    if args.dry_run:
        print(f"{args.experiment}: {len(points)} point(s), kind={cfg['kind']}")
        for params, pcfg in points:
            print(f"  {config.point_name(params)}")
            if cfg["kind"] == "server_load":
                print(f"    {shlex.join(build_args(pcfg['server']))}")
        return 0

    run_dir = storage.new_run_dir(results_dir, args.experiment)
    if args.keep:
        (run_dir / ".keep").touch()
    manifest = {"suite": "engine", "target": "llama-server direct (no router)",
                "system": sysinfo.collect(cfg), "config": cfg, "sweep": sweep,
                "overrides": args.overrides, "argv": sys.argv}
    if cfg["kind"] == "llama_bench":
        manifest["system"]["memcopy_1thread_gb_s"] = bench.memcopy_gb_s()
    storage.write_json(run_dir / "manifest.json", manifest)
    print(f"run dir: {run_dir}  ({len(points)} point(s))")

    rows = []
    try:
        for n, (params, pcfg) in enumerate(points, 1):
            name = config.point_name(params)
            point_dir = run_dir / name
            point_dir.mkdir()
            print(f"[{n}/{len(points)}] {name} ...", flush=True)
            row = {"suite": "engine"} | {k.split(".")[-1]: v for k, v in params.items()}
            free = sysinfo.mem_available_mib()
            if free < cfg["guards"]["min_free_ram_mib"]:
                row["status"] = f"skipped: MemAvailable {free} MiB"
            else:
                try:
                    runner = run_bench_point if cfg["kind"] == "llama_bench" else run_server_point
                    row |= {"status": "ok"} | runner(pcfg, point_dir)
                except Exception as exc:  # keep sweeping; the failure is recorded
                    row["status"] = f"error: {type(exc).__name__}: {exc}"
                    (point_dir / "error.txt").write_text(traceback.format_exc())
                    print(f"    {row['status']}")
            storage.write_json(point_dir / "summary.json", {"params": params, **row})
            rows.append({k: v for k, v in row.items() if not k.startswith("_")})
            storage.write_csv(run_dir / "summary.csv", rows)  # rewrite as we go: partial runs stay useful
    except KeyboardInterrupt:
        print("\ninterrupted - partial results kept")

    print()
    print_table(rows, list(sweep))
    print(f"\nresults: {run_dir}  ({storage.dir_size(run_dir) / 1e6:.1f} MB)")
    for run in storage.prune(results_dir, args.experiment, st["keep_raw_runs"]):
        print(f"pruned raw files: {run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
