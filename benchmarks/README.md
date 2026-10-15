# benchmarks/

Load-test harness, sweep configs, results with full provenance, charts and cost model. GPU numbers come only from real T4 runs.

Two benchmark **suites**, deliberately kept apart so a number is never quoted out of scope:

| Suite | Path under test | Answers | Status |
|---|---|---|---|
| [engine/](engine/) | client -> one inference server (llama-server, later vLLM), direct | What can this backend/model/quant do on its own? Slots, context cost, prefill/decode speed, bandwidth, what its metrics mean. | CPU llama.cpp experiments in place; GPU (T4, vLLM + llama.cpp CUDA) in [results/t4/](results/t4/README.md) |
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

## T4 engine track (Kaggle)

Real GPU numbers: vLLM (and llama.cpp CUDA) on a free Kaggle T4, driven from this machine.
Results, versions and caveats: [results/t4/README.md](results/t4/README.md). Tables: [results/t4/summary.md](results/t4/summary.md),
[kv_capacity_table.md](kv_capacity_table.md).

| File | What |
|---|---|
| [kaggle/run_kaggle.py](kaggle/run_kaggle.py) | push one stage as a private GPU kernel, poll, download into `results/t4/<run-id>/` (`make t4-run STAGE=...`) |
| [kaggle/t4_notebook.py](kaggle/t4_notebook.py) | runs inside the kernel: stages `smoke`, `baseline`, `kvgrid`, `sweep`, `quant`; JSONL rows with provenance, skip-if-done |
| [gpu_sampler.py](gpu_sampler.py) | NVML at 1 Hz → CSV (util.gpu, util.memory, memory used, power, SM clock, temperature); started/stopped around every load point |
| [analyze.py](analyze.py) | JSONL → charts + `results/t4/summary.md` + `kv_capacity_table.md` |
| [cost.py](cost.py) | $/1M output tokens from measured tok/s and a cited price |

**GPU utilisation caveat.** NVML `util.gpu` is the fraction of time *a kernel was running*, not SM activity:
one small kernel on one SM reads 100 %. `util.memory` is likewise "time memory was read/written", not bandwidth.
DCGM's profiling metrics (`SM_ACTIVE`, `SM_OCCUPANCY`, `DRAM_ACTIVE`) would answer the real question, but DCGM
is not available on Kaggle: the smoke stage found no `dcgmi`, no `nv-hostengine` and no `libdcgm*`
([smoke dcgm probe](results/t4/20261014-213711_smoke/results/smoke/logs/dcgm.txt)). So all GPU-side numbers
here are NVML samples, labelled `gpu_*`.
