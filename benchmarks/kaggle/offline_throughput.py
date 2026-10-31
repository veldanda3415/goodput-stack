"""`vllm bench throughput`, plus the engine's own Prometheus metrics sampled at 1 Hz (runs inside the Kaggle kernel).

    python -m benchmarks.kaggle.offline_throughput OUT.json -- <vllm bench throughput args>

The offline benchmark has no /metrics endpoint. This calls the same code the CLI calls
(vllm/entrypoints/cli/benchmark/throughput.py: `add_cli_args(parser)` then `main(args)`, vLLM 0.31.0), with the same
argument parser, and a background thread reads the in-process registry with `vllm.v1.metrics.reader.get_metrics_snapshot()`
(stats are on: bench's EngineArgs leave `disable_log_stats` False, and `LLM.from_engine_args` passes it through).
OUT.json: argv, start/end time, 1 Hz samples {metric name -> value} (counters and gauges summed over labels,
histograms as _count/_sum) and a final snapshot. The bench's own results go to its --output-json as usual.
"""

from __future__ import annotations

import json
import sys
import threading
import time


def snapshot() -> dict:
    from vllm.v1.metrics.reader import Counter, Gauge, Histogram, get_metrics_snapshot
    out: dict = {}
    for m in get_metrics_snapshot():
        if isinstance(m, (Counter, Gauge)):
            out[m.name] = out.get(m.name, 0) + m.value
        elif isinstance(m, Histogram):
            out[m.name + "_count"] = out.get(m.name + "_count", 0) + m.count
            out[m.name + "_sum"] = out.get(m.name + "_sum", 0) + m.sum
    return out


def main() -> None:
    out_path, argv = sys.argv[1], sys.argv[2:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    from vllm.benchmarks.throughput import add_cli_args, main as bench_main
    from vllm.utils.argparse_utils import FlexibleArgumentParser
    parser = FlexibleArgumentParser(prog="vllm bench throughput")
    add_cli_args(parser)
    args = parser.parse_args(argv)
    samples: list[dict] = []
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(1.0):
            try:
                samples.append({"t_unix": time.time(), "metrics": snapshot()})
            except Exception as exc:   # registry not populated yet, etc.
                samples.append({"t_unix": time.time(), "error": repr(exc)[:200]})

    th = threading.Thread(target=loop, daemon=True)
    th.start()
    t0 = time.time()
    try:
        bench_main(args)
    finally:
        stop.set()
        th.join(5)
        try:
            final = snapshot()
        except Exception as exc:
            final = {"error": repr(exc)[:200]}
        with open(out_path, "w") as f:
            json.dump({"argv": argv, "t_start_unix": t0, "t_end_unix": time.time(), "final": final,
                       "samples": samples}, f)


if __name__ == "__main__":
    main()
