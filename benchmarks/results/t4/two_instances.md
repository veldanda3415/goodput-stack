# Two vLLM instances on one T4 — what sharing one GPU costs (Kaggle T4, real)

Part B of the T4 ridge work. Two `vllm serve` processes of Qwen/Qwen2.5-3B-Instruct-AWQ on the **same** T4 (GPU 0
of the Kaggle VM), first with plain CUDA time-sharing, then under NVIDIA MPS, against one instance alone.

## Setup

- Model: `Qwen/Qwen2.5-3B-Instruct-AWQ` @ `3559b226e8ce77211e2c1bd7ddfb7686fec4d6dd` (FP16 weights twice won't fit in 15 GiB).
- vLLM 0.31.0, `--dtype half --no-enable-prefix-caching --revision <sha>`, `--gpu-memory-utilization` 0.90 (one
  instance) or 0.45 each (two instances), everything else default.
- Workload, identical in every condition: prompt 128 / output 256 tokens, ignore_eos, temperature 0, streamed
  `/v1/completions`, closed loop, repo harness (`benchmarks/harness`), one client process per instance.
- **Memory is not isolated between the two processes.** Each process must set its own fraction, and the second must
  start after the first has allocated: vLLM checks and profiles the GPU's free memory at start-up, so it only sees
  what the first instance left. Nothing stops a process from asking for more than is left except that start-up check.

**AWQ weight size used for the predictions: 1.95 GiB**, from the startup log of a single vLLM 0.31.0 instance of this
exact revision (run 20261014-224513_quant, `logs/server-awq-int4.log`: `Model loading took 1.95 GiB memory`; same run:
`Available KV cache memory: 9.86 GiB`, `GPU KV cache size: 287,072 tokens` at 0.90). KV bytes/token are FP16:
2 × 36 layers × 2 KV heads × 128 × 2 B = 36,864 B (same as the FP16 model; 9.86 GiB ÷ 36,864 B = 287,193 ✓).

## Predictions (written before any Part B run)

- Per instance at `--gpu-memory-utilization 0.45`: KV tokens = (15 GiB × 0.45 − 1.95 GiB − 1.7 GiB) ÷ 36,864 B
  = 3.10 GiB ÷ 36,864 B ≈ **90,300 tokens**. CALCULATED from the measured weight size (15 GiB = 15,360 MiB, the T4's
  NVML total). Check of the 1.7 GiB working-memory term against the 0.90 run: 13.5 − 1.95 − 9.86 = 1.69 GiB.
  One instance at 0.90 for comparison: ≈ 286,900 tokens CALCULATED (measured earlier: 287,072).
- Combined output of two instances (16 users each) vs one instance at 0.90 with 32 users: **combined ≤ single**
  (weights read twice per pair of steps, kernels interleave rather than overlap under plain time-sharing).
- MPS somewhat better than plain time-sharing.
- Per-user ITL worse when both are busy than when one is idle.
- Starting instance 2 with 0.90 while instance 1 holds its 0.45: start-up failure (vLLM's free-memory check).

## Decisions made

- **No separate smoke push for the weight size.** The assignment asks for the AWQ weight size from a single-instance
  startup log first; that log already exists for the same model revision and the same vLLM version (run
  20261014-224513), so the predictions use it, and the Part B session re-measures it in its own baseline startup
  log. This saves one install (~4–5 min of Kaggle GPU time).
