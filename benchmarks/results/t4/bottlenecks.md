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

Not run yet.

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
