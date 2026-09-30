# benchmarks/

Load-test harness, sweep configs, results with full provenance, charts and cost model. GPU numbers come only from real T4 runs.

Two benchmark **suites**, deliberately kept apart so a number is never quoted out of scope:

| Suite | Path under test | Answers | Status |
|---|---|---|---|
| [engine/](engine/) | client -> one inference server (llama-server, later vLLM), direct | What can this backend/model/quant do on its own? Slots, context cost, prefill/decode speed, bandwidth, what its metrics mean. | CPU llama.cpp experiments in place |
| [system/](system/) | client -> router -> backends on k8s (+ autoscaling) | What do users actually get, within the latency SLO, at what cost? | Week 5 |

```
benchmarks/
  harness/     shared library, target-agnostic: streaming client, stats, storage, provenance
  engine/      engine suite: server lifecycle, llama-bench wrapper, runner, configs/
  system/      system suite (router / k8s), later
  results/
    engine/    <timestamp>_<experiment>/ ...
    system/
  notebooks/
```

Every result records its suite in `manifest.json` (`"suite": "engine"`) and in each
`summary.csv` row. Raw per-request data and logs are git-ignored and pruned; summaries,
manifests and per-point `summary.json` are committed. Storage policy: [engine/README.md](engine/README.md#results-and-storage).

```bash
make venv                        # once
make bench-engine-list
make bench-engine EXP=smoke
```
