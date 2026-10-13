# benchmarks/

Load-test harness, sweep configs, results with full provenance, charts and cost model. GPU numbers come only from real T4 runs.

Two benchmark **suites**, deliberately kept apart so a number is never quoted out of scope:

| Suite | Path under test | Answers | Status |
|---|---|---|---|
| [engine/](engine/) | client -> one inference server (llama-server, later vLLM), direct | What can this backend/model/quant do on its own? Slots, context cost, prefill/decode speed, bandwidth, what its metrics mean. | CPU llama.cpp experiments in place |
| engine, simulated ([configs/sim.yaml](engine/configs/sim.yaml)) | client -> vLLM simulator pod in k3s (Service ClusterIP) | Does the measurement path report the latency the simulator was told to produce? How far is a calibrated linear model from the real engine? **Never engine performance.** | smoke/ttft/slot_limit/ttft_load/saturation |
| [system/](system/) | client -> agentgateway + llm-d EPP -> backends on k8s (+ autoscaling) | What do users actually get, within the latency SLO, at what cost? | planned |

```
benchmarks/
  harness/     shared library, target-agnostic: streaming client, stats, storage, provenance
  engine/      engine suite: server lifecycle, llama-bench wrapper, runner, configs/
  system/      system suite (gateway / k8s), later
  results/
    engine/    <timestamp>_<experiment>/ ...
    sim/       same layout, simulator runs (kept apart from real numbers)
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
make bench-sim EXP=smoke         # same harness against the in-cluster vLLM simulator
```
