# Where the throughput goes — Qwen2.5-3B FP16 on one T4 (Kaggle T4, real)

Question: Build 14 measured **1,458.6 output tok/s** offline at max-num-seqs 384 (in 128 / out 256, util 0.95,
max-num-batched-tokens 8,192) on one Kaggle T4. The datasheet roofline predicted **≈ 7,000** (CALCULATED in
[ridge.md](ridge.md)). This file splits that gap into measured parts.

Every measured number below comes from a JSONL row or a raw file in a run directory, with the command that made it.
Numbers marked CALCULATED are arithmetic on measured numbers or on the model config. Anything not measured goes into a
"residual / unexplained" line.

## Predictions (written before any Part G run, verbatim from the assignment)

- Throttle reason under sustained vLLM load: sw_power_cap active most of the time; power.limit = 70 W; thermal reasons rare.
- Memory bandwidth (large device-to-device copy / triad): 220–260 GB/s (75–85 % of 300).
- Large FP16 GEMM (8192³, cuBLAS via torch.matmul) sustained for 60 s: 20–40 TFLOP/s with SM clock near 1 GHz under the power cap; short bursts higher before the clock drops.
- Qwen-shaped GEMMs at decode batch sizes (M = 64…512): well below the large-GEMM rate at M = 64, approaching it by M = 384–512.
- Decode-only run (input 1–16 tokens, output 512, ignore_eos) at max-num-seqs 384: output tok/s clearly above the mixed 1,459 (no prompt compute).
- Profile at max-num-seqs 384: GEMMs 50–65 % of GPU time, attention 15–25 %, the rest elementwise/sampling; GPU idle gaps between kernels < 10 % of step time at 384 but larger at 64.
- CUDA graphs off (`--enforce-eager`): lower throughput, larger penalty at small batch.
- If clock locking is permitted: output tok/s roughly proportional to SM clock (compute-bound).
- Cross-session / cross-card variance in sustained SM clock: up to ±20 %.

## Setup

- Model: `Qwen/Qwen2.5-3B-Instruct` @ `aa8e72537993ba99e69dfaafa59ed015b17504d1`. Its config.json (fetched at that
  revision; also saved in-session as `logs/model-config.json`) gives: 36 layers, hidden 2048, 16 query heads, 2 KV
  heads (head_dim 2048 / 16 = 128), intermediate 11,008, vocab 151,936, `tie_word_embeddings: true`.
- Engine: vLLM 0.31.0, `--dtype half`, everything as in Build 14 unless a row says otherwise.
- Instrumentation (G0): [benchmarks/gpu_sampler.py](../../gpu_sampler.py) now samples, at 2 Hz by default, the old
  NVML columns plus `nvidia-smi --query-gpu` fields named exactly as `nvidia-smi --help-query-gpu` lists them on the
  machine (clocks, power draw and limits, temperature, pstate, every clock-throttle / clock-event reason).
  `nvidia-smi -q -d PERFORMANCE,POWER,CLOCK,TEMPERATURE` is saved before and after every load run.
- Kaggle stage: `bneck` in [t4_notebook.py](../../kaggle/t4_notebook.py), one ordered `--plan` per session.

## Decisions made

- **The new stage has a plan per session.** Part G is split into a few Kaggle sessions. Each one runs the reference
  point (G4) at its start and end. The budget guard always keeps time for the end reference.
- **Profiling uses vLLM's own torch profiler.** In vLLM 0.31.0 that is `--profiler-config` (a `ProfilerConfig`,
  `vllm/config/profiler.py`) together with `vllm bench throughput --profile`. The config sets `delay_iterations` /
  `max_iterations`, so the trace covers a window of steady-state steps (300 steps skipped, then 300 at 384 / 400 at 64).
  `detailed_trace_annotation` puts each step's scheduled token and request counts into its annotation name
  (`vllm/v1/worker/gpu_worker.py`, `annotate_profile`). `VLLM_CUSTOM_SCOPES_FOR_PROFILING=1` (`vllm/envs.py`) adds the
  runner's forward / postprocess / sample scopes. Stack recording is off and the front end is ignored to keep the
  overhead low. The profiled run's tok/s is not used as a speed number: the profiler and the trace export slow it.
  Unprofiled runs give the speed.
- **The x-axis label fix goes into [report_ridge.py](../../kaggle/report_ridge.py).** The assignment names
  `benchmarks/analyze.py`, but the Build 14 ridge chart is drawn by `benchmarks/kaggle/report_ridge.py`.

## G0 — instrumentation and tool availability

Smoke run **20261031-192426_bneck** (Kaggle T4, real; 51 s of session = 0.014 GPU-h; git `b29d107`; Tesla T4 GPU 0
`GPU-102fc0c7-3bc4-bf6a-d730-8db13e0984bd`, driver 580.178.04, CUDA 13.0 (driver); Kaggle's own torch 2.11.0+cu128, no
vLLM). Command: `make t4-run STAGE=bneck ARGS='--args "--plan tools,micro:0 --no-install --micro-quick --budget-h 0.2"'`.
Raw files: `results/bneck/bneck.jsonl` row `tools`, `results/bneck/logs/`.

**Sampler fields.** `nvidia-smi --help-query-gpu` on this driver lists every wanted field
([logs/nvidia-smi-help-query-gpu.txt](20261031-192426_bneck/results/bneck/logs/nvidia-smi-help-query-gpu.txt)).
Reason fields are listed as `clocks_event_reasons.X` with `clocks_throttle_reasons.X` as the alias; the sampler uses
the throttle name. There are 10 of them: `supported`, `active` (hex bitmasks), `gpu_idle`, `applications_clocks_setting`,
`sw_power_cap`, `hw_slowdown`, `hw_thermal_slowdown`, `hw_power_brake_slowdown`, `sw_thermal_slowdown`, `sync_boost`.
`power.draw.average` reads `[N/A]` on this card; `power.draw` and `power.draw.instant` return values. Unit tests:
[benchmarks/tests/test_gpu_sampler.py](../../tests/test_gpu_sampler.py).

**Limits read-only** (`nvidia-smi -i 0 --query-gpu=power.limit,...`): power.limit 70.00 W, enforced 70.00 W, default
70.00 W, min 60.00 W, max 70.00 W; clocks.max.sm 1,590 MHz; clocks.applications.graphics 585 MHz; persistence mode
Disabled; compute mode Default. `nvidia-smi -q -d SUPPORTED_CLOCKS` lists graphics clocks 300–1,590 MHz in 15 MHz steps.
The container runs as uid 0 (root).

| tool / command | permitted? | exact result |
|---|---|---|
| `dcgmi` (DCGM SM-active / tensor-active) | **no: not installed** | not on PATH, not in /usr/local/cuda*/bin or /opt/nvidia/*/bin; `nv-hostengine` also absent |
| `nsys` | **no: not installed** | not found in the same places |
| `ncu` | **installed, not usable** | `/usr/local/cuda/bin/ncu` "Version 2025.1.1.0"; profiling a 2048² FP16 matmul: `==ERROR== ERR_NVGPUCTRPERM - The user does not have permission to access NVIDIA GPU Performance Counters on the target device 0.` (rc 1) |
| `nvidia-smi -i 0 -pl 60.00` | **no** | `Failed to set power management limit for GPU 00000000:00:04.0: Insufficient Permissions` (rc 4); the reset to 70.00 failed the same way; the limit read back 70.00 W |
| `nvidia-smi -i 0 -lgc 1590,1590` | **no** | `The current user does not have permission to change clocks for GPU 00000000:00:04.0.` (rc 4); `-rgc` the same |

GPU state was not changed: both writes were refused. The `-rgc` that the stage runs on exit is a no-op here.
Consequences: G3.7 (clock locking) cannot run. DCGM SM-active and Nsight counters are not available. The profile in G2
uses the torch profiler (CUPTI activity tracing, which needs no counter permission).

## G1 — hardware ceilings without vLLM

Not run yet.

## G2 — where vLLM's step time goes

Not run yet.

## G3 — engine-side ablations

Not run yet.

## G4 — variance

Not run yet.

## G5 — the gap, decomposed

Not run yet.
