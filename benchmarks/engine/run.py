"""Engine benchmark runner: for each sweep point, start a fresh llama-server,
drive load DIRECTLY against it (no router), collect metrics, stop it, write results.

    python -m benchmarks.engine.run ttft
    python -m benchmarks.engine.run slot_limit --set client.requests=8 --set server.threads=4
    python -m benchmarks.engine.run ttft --dry-run         # show points + server commands
    python -m benchmarks.engine.run --list
    python -m benchmarks.engine.run --prune ttft          # prune raw files only
    python -m benchmarks.engine.run --report benchmarks/results/engine/<run>   # rebuild REPORT.md
    python -m benchmarks.engine.run --all [--skip saturation]                    # whole batch + index
"""

from __future__ import annotations

import argparse
import json
import asyncio
import shlex
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from ..harness import client, config, report, stats, storage, sysinfo
from . import bench
from .server import LlamaServer, build_args, probe_memory

DEFAULT_CONFIG = Path(__file__).resolve().parent / "configs" / "llamacpp.yaml"

def run_server_point(cfg: dict, point_dir: Path) -> dict:
    probe = probe_memory(cfg, point_dir) if cfg["server"].get("probe_memory") else {}
    with LlamaServer(cfg, point_dir) as srv:
        result = asyncio.run(client.run_point(srv.base_url, cfg))
    storage.write_jsonl(point_dir / "requests.jsonl", result["records"])
    storage.write_jsonl(point_dir / "metrics.jsonl", result["samples"] + [{"idle_probe": result["idle_probe"]}])
    row = stats.summarize_load(result, cfg.get("slo"))
    mem = srv.memory_info()
    row |= {k: v for k, v in mem.items() if k != "log_memory_lines"}
    return row | probe | {"_memory_lines": mem["log_memory_lines"]}


def run_bench_point(cfg: dict, point_dir: Path) -> dict:
    rows = bench.run_llama_bench(cfg)
    storage.write_jsonl(point_dir / "bench.jsonl", rows)
    return bench.summarize_bench(rows)


def run_once(cfg: dict, point_dir: Path) -> dict:
    try:
        runner = run_bench_point if cfg["kind"] == "llama_bench" else run_server_point
        return {"status": "ok"} | runner(cfg, point_dir)
    except Exception as exc:  # keep sweeping; the failure is recorded
        (point_dir / "error.txt").write_text(traceback.format_exc())
        print(f"    error: {type(exc).__name__}: {exc}")
        return {"status": f"error: {type(exc).__name__}: {exc}"}


def run_repeats(cfg: dict, point_dir: Path) -> dict:
    """Run a point `repeats` times, each on a fresh server, in rep-N/ subdirs; combine."""
    n = cfg.get("repeats") or 1
    if n == 1:
        return run_once(cfg, point_dir)
    reps = []
    for i in range(1, n + 1):
        rep_dir = point_dir / f"rep-{i}"
        rep_dir.mkdir()
        # memory probe only needs one start; later repeats skip it
        rep_cfg = cfg if i == 1 else {**cfg, "server": {**cfg["server"], "probe_memory": False}}
        rep = run_once(rep_cfg, rep_dir)
        storage.write_json(rep_dir / "summary.json", rep)
        reps.append({k: v for k, v in rep.items() if not k.startswith("_")})
        print(f"    rep {i}/{n}: {rep['status']}", flush=True)
    return stats.combine_repeats(reps)


class Interrupted(Exception):
    """Ctrl-C during an experiment: partial results were written; stop any batch."""


def run_experiment(doc: dict, experiment: str, overrides: list[str], keep: bool = False) -> Path:
    cfg, sweep = config.resolve(doc, experiment, overrides)
    points = config.expand(cfg, sweep)
    st = cfg["storage"]
    results_dir = Path(st["results_dir"])

    run_dir = storage.new_run_dir(results_dir, experiment)
    if keep:
        (run_dir / ".keep").touch()
    manifest = {"suite": "engine", "target": "llama-server direct (no router)",
                "system": sysinfo.collect(cfg), "config": cfg, "sweep": sweep,
                "overrides": overrides, "argv": sys.argv}
    if cfg["kind"] == "llama_bench":
        manifest["system"]["memcopy_1thread_gb_s"] = bench.memcopy_gb_s()
    storage.write_json(run_dir / "manifest.json", manifest)
    print(f"run dir: {run_dir}  ({len(points)} point(s))")

    rows = []
    interrupted = False
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
                row |= run_repeats(pcfg, point_dir)
            storage.write_json(point_dir / "summary.json", {"params": params, **row})
            rows.append({k: v for k, v in row.items() if not k.startswith("_")})
            storage.write_csv(run_dir / "summary.csv", rows)  # rewrite as we go: partial runs stay useful
    except KeyboardInterrupt:
        interrupted = True
        print("\ninterrupted - partial results kept")

    print()
    print(report.terminal_table(rows, cfg, sweep))
    if rows:
        print(f"\nreport:  {report.write(run_dir, rows)}")
    print(f"results: {run_dir}  ({storage.dir_size(run_dir) / 1e6:.1f} MB)")
    for run in storage.prune(results_dir, experiment, st["keep_raw_runs"]):
        print(f"pruned raw files: {run}")
    if interrupted:
        raise Interrupted(run_dir)
    return run_dir


def run_all(doc: dict, experiments: list[str], overrides: list[str], keep: bool) -> Path:
    """Run experiments back to back; one failing never stops the rest. Writes an index."""
    results_dir = Path(doc["defaults"]["storage"]["results_dir"])
    results_dir.mkdir(parents=True, exist_ok=True)
    index = results_dir / f"{datetime.now():%Y%m%d-%H%M%S}_ALL.md"
    done: list[tuple[str, str, Path | None, float]] = []
    t_all = time.monotonic()

    def write_index() -> None:
        index.write_text(report.render_index(done, time.monotonic() - t_all))

    for i, name in enumerate(experiments, 1):
        print(f"\n{'=' * 70}\n== [{i}/{len(experiments)}] {name}\n{'=' * 70}", flush=True)
        t0 = time.monotonic()
        try:
            run_dir = run_experiment(doc, name, overrides, keep)
            done.append((name, "ok", run_dir, time.monotonic() - t0))
        except Interrupted as exc:
            done.append((name, "interrupted", Path(str(exc)), time.monotonic() - t0))
            write_index()
            print(f"\nbatch stopped. index: {index}")
            raise SystemExit(130)
        except Exception as exc:  # e.g. port busy, bad config: record and move on
            traceback.print_exc()
            done.append((name, f"failed: {type(exc).__name__}: {exc}", None, time.monotonic() - t0))
        write_index()  # rewrite after each experiment: progress is visible, partial batches useful
    print(f"\nindex: {index}")
    return index


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment", nargs="?")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="mark this run so retention never prunes it")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--prune", action="store_true", help="only prune raw files of old runs")
    ap.add_argument("--report", type=Path, metavar="RUN_DIR", help="regenerate REPORT.md for an existing run")
    ap.add_argument("--all", action="store_true", help="run every experiment in `batch:` order, then write an index")
    ap.add_argument("--skip", action="append", default=[], metavar="EXP", help="with --all: leave this experiment out")
    args = ap.parse_args(argv)

    doc = config.load(args.config)

    if args.report:
        # use the CURRENT report layout from the YAML, so report fixes apply to old runs too
        exp = json.loads((args.report / "manifest.json").read_text())["config"]["experiment"]
        print(report.write(args.report, view=doc["experiments"].get(exp, {}).get("report")))
        return 0

    if args.all:
        order = doc.get("batch") or [e for e in doc["experiments"] if e != "smoke"]
        names = [e for e in order if e not in args.skip]
        if args.dry_run:
            for name in names:
                cfg, sweep = config.resolve(doc, name, args.overrides)
                print(f"{name:20s} {len(config.expand(cfg, sweep))} point(s) x {cfg.get('repeats') or 1} repeat(s)")
            return 0
        run_all(doc, names, args.overrides, args.keep)
        return 0

    if args.list or not args.experiment:
        for name, exp in doc["experiments"].items():
            print(f"{name:20s} {' '.join((exp.get('description') or '').split())}")
        return 0

    cfg, sweep = config.resolve(doc, args.experiment, args.overrides)
    points = config.expand(cfg, sweep)

    if args.prune:
        st = cfg["storage"]
        for run in storage.prune(Path(st["results_dir"]), args.experiment, st["keep_raw_runs"]):
            print(f"pruned raw files: {run}")
        return 0

    if args.dry_run:
        print(f"{args.experiment}: {len(points)} point(s), kind={cfg['kind']}")
        for params, pcfg in points:
            print(f"  {config.point_name(params)}")
            if cfg["kind"] == "server_load":
                print(f"    {shlex.join(build_args(pcfg['server']))}")
        return 0

    try:
        run_experiment(doc, args.experiment, args.overrides, args.keep)
    except Interrupted:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
