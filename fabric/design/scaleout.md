# Scale-out calculator: a faster GPU hands the bottleneck to the fabric (CALCULATED)

Everything in this file is **CALCULATED** by [scaleout.py](scaleout.py) from (a) measured numbers that it **reads from
this repo's result files** (T4 step times, the Build 7b PCIe fit, the E3 Soft-RoCE rate) and (b) cited specs in
[sources.md](sources.md). Nothing here was measured in Build 17. Regenerate (tables between the markers):

    .venv/bin/python -m fabric.design.scaleout          # --check fails if this file is stale

Inputs: `scaleout:` in [inputs.yaml](inputs.yaml). Tests: [tests/test_scaleout.py](tests/test_scaleout.py).

## Models (config.json at a pinned revision; S22, S23)

Saved copies: [models/](models/). Neither config has a `head_dim` field, so head_dim = hidden_size ÷ num_attention_heads.

<!-- scaleout:models -->
| Model | Revision | num_hidden_layers | hidden_size | num_attention_heads | num_key_value_heads | head_dim |
|---|---|---:|---:|---:|---:|---|
| Qwen2.5-3B-Instruct | `aa8e72537993ba99e69dfaafa59ed015b17504d1` | 36 | 2,048 | 16 | 2 | 128 (hidden_size / num_attention_heads) |
| Qwen2.5-72B-Instruct | `495f39366efef23836d0cfae4fbe635880d2be31` | 80 | 8,192 | 64 | 8 | 128 (hidden_size / num_attention_heads) |
<!-- /scaleout -->

## Link models

Per GPU, per direction. All-reduce is a ring: **T = 2(N−1)·α + 2(N−1)/N · S / B** per all-reduce (collectives.py
`ring_allreduce_time`; B is the ring's busbw, which by definition does not depend on N). N-dependence used: the latency
term grows linearly in N, the bandwidth term as 2(N−1)/N.

<!-- scaleout:links -->
| Link | B (GB/s per GPU, ring busbw) | α (µs per ring step) | Source |
|---|---:|---|---|
| PCIe via host memory (2×T4, MEASURED fit) | 3.89 | 8.66 | Build 7b nccl_check fit of benchmarks/results/t4/20261016-153016_nccl: B = 1 GiB busbw 3.89 GB/s, α = t0/2 = 8.66 µs |
| NVLink 4 (H100) | 360.00 | 1.00 | S3/S4: 450 GB/s per direction × 0.80 (A2), α 1.0 µs (A4) |
| 400G RoCE / IB per GPU | 40.00 | 5.00 | S1/S8: 400 Gb/s line rate × 0.80 (A1) = 40 GB/s, α 5.0 µs (A3) |
| Soft-RoCE, lab VMs (E3, MEASURED; KV transfer only) | 0.0750 | 0 (not separated) | E3 `ib_write_bw` 1 MiB, median of [0.62, 0.57, 0.6] Gbit/s = 0.6 Gbit/s (fabric/experiments/e3-results.json) |
<!-- /scaleout -->

- **PCIe** is the only link with a measured fit, and it was fitted at **N = 2 only** (two T4s, NCCL over SHM through host
  memory). Using it for TP 4 and 8 assumes every ring hop gets the same 3.89 GB/s; on a real host with more GPUs behind
  the same bridges it would likely be lower. That is an assumption, not a measurement.
- **NVLink** and **400G** use the repo's existing efficiency (0.80, A1/A2) and α (A3/A4); the 400G row is shown at that
  efficiency only. TP over a 400G scale-out network (one GPU per node in the TP ring) is not how TP is normally placed;
  the row shows what the fabric would carry if it were.
- **Soft-RoCE** (E3) is two lab VMs over the emulated spine, CPU-bound; it is used only for KV transfer, bandwidth only
  (its latency was not measured separately from the 1 MiB transfer).

## Compute time per decode step (T4, measured, Qwen2.5-3B-Instruct fp16, TP 1)

<!-- scaleout:compute -->
| Batch | T4 step ms (used) | How | File | Build 14 ridge, mixed prefill+decode (cross-check) |
|---:|---:|---|---|---|
| 1 | 26.91 | 1000 / batch-1 decode tok/s: `decode_tok_s_median` = 37.16, row `fp16-decode` | `benchmarks/results/t4/20261014-224513_quant/results/quant/quant.jsonl` | — |
| 64 | 60.62 | trace GPU step period, decode-only steps: `steps.decode_only.gpu_period_ms_mean` = 60.624 | `benchmarks/results/t4/20261031-192649_bneck/results/bneck/prof-mns64.breakdown.json` | 66.0 (row `offline-mns64`: 62.1 running ÷ 941.5 tok/s) |
| 384 | 208.01 | trace GPU step period, decode-only steps: `steps.decode_only.gpu_period_ms_mean` = 208.013 | `benchmarks/results/t4/20261031-192649_bneck/results/bneck/prof-mns384.breakdown.json` | 249.9 (row `offline-mns384`: 364.5 running ÷ 1,458.6 tok/s) |
<!-- /scaleout -->

- The used value is the decode-only GPU step period from the Build 16 G2 trace (batch 64, 384) and 1,000 ÷ the batch-1
  decode rate (quant run, row `fp16-decode`) for batch 1. The Build 14 ridge column is mixed prefill + decode
  (CALCULATED as running ÷ output tok/s, ridge.md's own method) and is longer; it is shown as a cross-check, not used.
- These are **whole-model, one-GPU** step times. With TP the per-GPU compute would shrink (by at most TP×); this file
  does not assume any TP speed-up. The ÷ 2 / ÷ 5 / ÷ 10 columns show what a shorter compute step does to the share.
- **No compute is measured for Qwen2.5-72B** (it does not fit on a T4), so its share columns are empty; the last column
  ("compute ms for share ≤ 10 %" = 9 × comm) says how long a step must be for the fabric to stay under 10 %.
- **H100 step time** is an input (`h100_step_ms`), empty until Modal run D measures it. It is not taken from datasheets.

## Bytes per decode step, tensor parallel (Megatron, S17)

Per layer, 2 all-reduces of the activations (after attention and after the MLP); decode has no backward pass. Message =
batch × hidden_size × 2 bytes (BF16/FP16). Wire bytes per GPU = messages × 2(N−1)/N × S (nccl-tests busbw factor, S15).

<!-- scaleout:bytes -->
| Model | Batch | Message B (batch × hidden × 2) | All-reduces / step (2 × layers) | Message MB / step | Wire MB / GPU / step, TP 2 | Wire MB / GPU / step, TP 4 | Wire MB / GPU / step, TP 8 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen2.5-3B-Instruct | 1 | 4,096 | 72 | 0.295 | 0.295 | 0.442 | 0.516 |
| Qwen2.5-3B-Instruct | 64 | 262,144 | 72 | 18.874 | 18.874 | 28.312 | 33.030 |
| Qwen2.5-3B-Instruct | 384 | 1,572,864 | 72 | 113.246 | 113.246 | 169.869 | 198.181 |
| Qwen2.5-72B-Instruct | 1 | 16,384 | 160 | 2.621 | 2.621 | 3.932 | 4.588 |
| Qwen2.5-72B-Instruct | 64 | 1,048,576 | 160 | 167.772 | 167.772 | 251.658 | 293.601 |
| Qwen2.5-72B-Instruct | 384 | 6,291,456 | 160 | 1,006.633 | 1,006.633 | 1,509.949 | 1,761.608 |
<!-- /scaleout -->

## Communication share of the step (no overlap: upper bound)

Comm share = comm ÷ (compute + comm).

<!-- scaleout:comm-share -->
| Model | Link | TP | Batch | Comm ms / step | T4 compute ms (measured, TP 1) | **Comm share, T4 measured** | share, T4 ÷ 2 (sensitivity, not a GPU claim) | share, T4 ÷ 5 (sensitivity, not a GPU claim) | share, T4 ÷ 10 (sensitivity, not a GPU claim) | Comm share, H100 | Compute ms for share ≤ 10 % |
|---|---|---:|---:|---:|---|---|---|---|---|---|---:|
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 1 | 1.322 | 26.91 | 4.7% | 8.9% | 19.7% | 32.9% | pending Modal run D | 11.90 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 64 | 6.104 | 60.62 | 9.1% | 16.8% | 33.5% | 50.2% | pending Modal run D | 54.94 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 384 | 30.40 | 208.01 | 12.7% | 22.6% | 42.2% | 59.4% | pending Modal run D | 273.56 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 1 | 3.853 | 26.91 | 12.5% | 22.3% | 41.7% | 58.9% | pending Modal run D | 34.68 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 64 | 11.03 | 60.62 | 15.4% | 26.7% | 47.6% | 64.5% | pending Modal run D | 99.24 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 384 | 47.46 | 208.01 | 18.6% | 31.3% | 53.3% | 69.5% | pending Modal run D | 427.16 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 1 | 8.857 | 26.91 | 24.8% | 39.7% | 62.2% | 76.7% | pending Modal run D | 79.71 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 64 | 17.23 | 60.62 | 22.1% | 36.2% | 58.7% | 74.0% | pending Modal run D | 155.03 |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 384 | 59.74 | 208.01 | 22.3% | 36.5% | 58.9% | 74.2% | pending Modal run D | 537.62 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 2 | 1 | 0.145 | 26.91 | 0.5% | 1.1% | 2.6% | 5.1% | pending Modal run D | 1.303 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 2 | 64 | 0.196 | 60.62 | 0.3% | 0.6% | 1.6% | 3.1% | pending Modal run D | 1.768 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 2 | 384 | 0.459 | 208.01 | 0.2% | 0.4% | 1.1% | 2.2% | pending Modal run D | 4.127 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 4 | 1 | 0.433 | 26.91 | 1.6% | 3.1% | 7.4% | 13.9% | pending Modal run D | 3.899 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 4 | 64 | 0.511 | 60.62 | 0.8% | 1.7% | 4.0% | 7.8% | pending Modal run D | 4.596 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 4 | 384 | 0.904 | 208.01 | 0.4% | 0.9% | 2.1% | 4.2% | pending Modal run D | 8.135 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 8 | 1 | 1.009 | 26.91 | 3.6% | 7.0% | 15.8% | 27.3% | pending Modal run D | 9.085 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 8 | 64 | 1.100 | 60.62 | 1.8% | 3.5% | 8.3% | 15.4% | pending Modal run D | 9.898 |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 8 | 384 | 1.559 | 208.01 | 0.7% | 1.5% | 3.6% | 7.0% | pending Modal run D | 14.03 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 2 | 1 | 0.727 | 26.91 | 2.6% | 5.1% | 11.9% | 21.3% | pending Modal run D | 6.546 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 2 | 64 | 1.192 | 60.62 | 1.9% | 3.8% | 9.0% | 16.4% | pending Modal run D | 10.73 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 2 | 384 | 3.551 | 208.01 | 1.7% | 3.3% | 7.9% | 14.6% | pending Modal run D | 31.96 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 4 | 1 | 2.171 | 26.91 | 7.5% | 13.9% | 28.7% | 44.7% | pending Modal run D | 19.54 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 4 | 64 | 2.868 | 60.62 | 4.5% | 8.6% | 19.1% | 32.1% | pending Modal run D | 25.81 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 4 | 384 | 6.407 | 208.01 | 3.0% | 5.8% | 13.3% | 23.5% | pending Modal run D | 57.66 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 8 | 1 | 5.053 | 26.91 | 15.8% | 27.3% | 48.4% | 65.2% | pending Modal run D | 45.48 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 8 | 64 | 5.866 | 60.62 | 8.8% | 16.2% | 32.6% | 49.2% | pending Modal run D | 52.79 |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 8 | 384 | 9.995 | 208.01 | 4.6% | 8.8% | 19.4% | 32.5% | pending Modal run D | 89.95 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 1 | 3.444 | — | — | — | — | — | pending Modal run D | 31.00 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 64 | 45.95 | — | — | — | — | — | pending Modal run D | 413.58 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 384 | 261.87 | — | — | — | — | — | pending Modal run D | 2,356.85 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 1 | 9.321 | — | — | — | — | — | pending Modal run D | 83.89 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 64 | 73.08 | — | — | — | — | — | pending Modal run D | 657.76 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 384 | 396.96 | — | — | — | — | — | pending Modal run D | 3,572.66 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 1 | 20.57 | — | — | — | — | — | pending Modal run D | 185.11 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 64 | 94.96 | — | — | — | — | — | pending Modal run D | 854.63 |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 384 | 472.82 | — | — | — | — | — | pending Modal run D | 4,255.35 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 2 | 1 | 0.327 | — | — | — | — | — | pending Modal run D | 2.946 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 2 | 64 | 0.786 | — | — | — | — | — | pending Modal run D | 7.074 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 2 | 384 | 3.116 | — | — | — | — | — | pending Modal run D | 28.05 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 4 | 1 | 0.971 | — | — | — | — | — | pending Modal run D | 8.738 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 4 | 64 | 1.659 | — | — | — | — | — | pending Modal run D | 14.93 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 4 | 384 | 5.154 | — | — | — | — | — | pending Modal run D | 46.39 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 8 | 1 | 2.253 | — | — | — | — | — | pending Modal run D | 20.27 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 8 | 64 | 3.056 | — | — | — | — | — | pending Modal run D | 27.50 |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 8 | 384 | 7.133 | — | — | — | — | — | pending Modal run D | 64.20 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 2 | 1 | 1.666 | — | — | — | — | — | pending Modal run D | 14.99 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 2 | 64 | 5.794 | — | — | — | — | — | pending Modal run D | 52.15 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 2 | 384 | 26.77 | — | — | — | — | — | pending Modal run D | 240.89 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 4 | 1 | 4.898 | — | — | — | — | — | pending Modal run D | 44.08 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 4 | 64 | 11.09 | — | — | — | — | — | pending Modal run D | 99.82 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 4 | 384 | 42.55 | — | — | — | — | — | pending Modal run D | 382.94 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 8 | 1 | 11.31 | — | — | — | — | — | pending Modal run D | 101.83 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 8 | 64 | 18.54 | — | — | — | — | — | pending Modal run D | 166.86 |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 8 | 384 | 55.24 | — | — | — | — | — | pending Modal run D | 497.16 |
<!-- /scaleout -->

**Reading it.**
- On the measured T4 numbers, the PCIe path already costs **9.1 %** of a batch-64 step at TP 2 and **22 %** at TP 8.
  Make compute 10× faster (sensitivity column) and the same PCIe all-reduce is **50–74 %** of the step: the GPU got
  faster, the link did not, and the link becomes the larger part of the step.
- NVLink keeps the 3B model's share ≤ 1.8 % at T4 compute and ≤ 15.4 % at ÷ 10 for batch ≥ 64; batch 1 is
  latency-bound (2(N−1) α per all-reduce × 72 all-reduces), not bandwidth-bound.
- 400G per GPU sits between: 1.7–15.8 % at T4 compute, 14.6–65.2 % at ÷ 10.
- Qwen2.5-72B (the model that needs TP): per decode step at batch 384, TP 8, comm is 7.1 ms on NVLink, 55.2 ms on
  400G and 473 ms on the PCIe fit. For the fabric to stay under 10 % of the step, the compute step would have to be
  ≥ 64 ms (NVLink) / ≥ 497 ms (400G). Whether an H100 step is shorter than that is what Modal run D has to measure.

## Prefill → decode KV transfer (disaggregated serving)

KV bytes per token = layers × 2 (K, V) × kv_heads × head_dim × 2 bytes. One prompt's KV moves once, prefill GPU →
decode GPU, as one point-to-point transfer: α + bytes ÷ B (collectives.py `p2p_time`).

<!-- scaleout:kv -->
| Model | KV B / token | Prompt tokens | KV MB / prompt | PCIe via host memory (2×T4, MEASURED fit) (ms) | NVLink 4 (H100) (ms) | 400G RoCE / IB per GPU (ms) | Soft-RoCE lab (E3, MEASURED) (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen2.5-3B-Instruct | 36,864 | 512 | 18.87 | 4.867 | 0.053 | 0.477 | 251.66 |
| Qwen2.5-3B-Instruct | 36,864 | 2,048 | 75.50 | 19.44 | 0.211 | 1.892 | 1,006.63 |
| Qwen2.5-3B-Instruct | 36,864 | 8,192 | 301.99 | 77.74 | 0.840 | 7.555 | 4,026.53 |
| Qwen2.5-72B-Instruct | 327,680 | 512 | 167.77 | 43.19 | 0.467 | 4.199 | 2,236.96 |
| Qwen2.5-72B-Instruct | 327,680 | 2,048 | 671.09 | 172.74 | 1.865 | 16.78 | 8,947.85 |
| Qwen2.5-72B-Instruct | 327,680 | 8,192 | 2,684.35 | 690.95 | 7.458 | 67.11 | 35,791.39 |
<!-- /scaleout -->

- The measured lab Soft-RoCE rate (0.6 Gbit/s, CPU-bound VMs) needs ~1 s to move one 2,048-token Qwen2.5-3B prompt —
  as long as ~37 batch-1 T4 decode steps (26.9 ms each). The emulated lab can show the protocol, not the rate.
- The GQA ratio matters more than size: Qwen2.5-3B's 2 KV heads give 36,864 B/token; 72B's 8 KV heads × 80 layers give
  327,680 B/token (8.9×).

## One slow link (50 %) in the TP ring

Method of DESIGN.md §2.3: the ring runs at its slowest link, so the bandwidth term becomes 2(N−1)/N · S / (f · B); α is
unchanged. Effect on comm and, for the measured 3B model, on the T4 step (compute + comm, no overlap).

<!-- scaleout:slow-link -->
| Model | Link | TP | Batch | Comm ms, healthy | Comm ms, one link at 50% | Comm change | T4 step ms (compute + comm), healthy → slow |
|---|---|---:|---:|---:|---:|---:|---|
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 64 | 6.104 | 10.96 | +79.6% | 66.73 → 71.59 (+7.3%) |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 384 | 30.40 | 59.54 | +95.9% | 238.41 → 267.56 (+12.2%) |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 64 | 11.03 | 18.31 | +66.1% | 71.65 → 78.94 (+10.2%) |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 384 | 47.46 | 91.19 | +92.1% | 255.48 → 299.20 (+17.1%) |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 64 | 17.23 | 25.73 | +49.4% | 77.85 → 86.35 (+10.9%) |
| Qwen2.5-3B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 384 | 59.74 | 110.75 | +85.4% | 267.75 → 318.76 (+19.1%) |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 2 | 64 | 0.196 | 0.249 | +26.7% | 60.82 → 60.87 (+0.1%) |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 2 | 384 | 0.459 | 0.773 | +68.6% | 208.47 → 208.79 (+0.2%) |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 4 | 64 | 0.511 | 0.589 | +15.4% | 61.13 → 61.21 (+0.1%) |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 4 | 384 | 0.904 | 1.376 | +52.2% | 208.92 → 209.39 (+0.2%) |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 8 | 64 | 1.100 | 1.192 | +8.3% | 61.72 → 61.82 (+0.1%) |
| Qwen2.5-3B-Instruct | NVLink 4 (H100) | 8 | 384 | 1.559 | 2.109 | +35.3% | 209.57 → 210.12 (+0.3%) |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 2 | 64 | 1.192 | 1.664 | +39.6% | 61.82 → 62.29 (+0.8%) |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 2 | 384 | 3.551 | 6.382 | +79.7% | 211.56 → 214.40 (+1.3%) |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 4 | 64 | 2.868 | 3.576 | +24.7% | 63.49 → 64.20 (+1.1%) |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 4 | 384 | 6.407 | 10.65 | +66.3% | 214.42 → 218.67 (+2.0%) |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 8 | 64 | 5.866 | 6.692 | +14.1% | 66.49 → 67.32 (+1.2%) |
| Qwen2.5-3B-Instruct | 400G RoCE / IB per GPU | 8 | 384 | 9.995 | 14.95 | +49.6% | 218.01 → 222.96 (+2.3%) |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 64 | 45.95 | 89.14 | +94.0% | — |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 2 | 384 | 261.87 | 520.97 | +98.9% | — |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 64 | 73.08 | 137.86 | +88.6% | — |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 4 | 384 | 396.96 | 785.62 | +97.9% | — |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 64 | 94.96 | 170.53 | +79.6% | — |
| Qwen2.5-72B-Instruct | PCIe via host memory (2×T4, MEASURED fit) | 8 | 384 | 472.82 | 926.25 | +95.9% | — |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 2 | 64 | 0.786 | 1.252 | +59.3% | — |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 2 | 384 | 3.116 | 5.912 | +89.7% | — |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 4 | 64 | 1.659 | 2.358 | +42.1% | — |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 4 | 384 | 5.154 | 9.349 | +81.4% | — |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 8 | 64 | 3.056 | 3.871 | +26.7% | — |
| Qwen2.5-72B-Instruct | NVLink 4 (H100) | 8 | 384 | 7.133 | 12.03 | +68.6% | — |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 2 | 64 | 5.794 | 9.989 | +72.4% | — |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 2 | 384 | 26.77 | 51.93 | +94.0% | — |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 4 | 64 | 11.09 | 17.38 | +56.7% | — |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 4 | 384 | 42.55 | 80.30 | +88.7% | — |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 8 | 64 | 18.54 | 25.88 | +39.6% | — |
| Qwen2.5-72B-Instruct | 400G RoCE / IB per GPU | 8 | 384 | 55.24 | 99.28 | +79.7% | — |
<!-- /scaleout -->

- Bandwidth-bound cases (large batch, slow link) approach the plain-ring 2× (+100 %); α-bound cases (small batch, fast
  link) change less. On the step, the effect is the comm share × the comm change: +12–19 % per step at batch 384 over
  PCIe, ≤ +2.3 % over 400G, ≤ +0.3 % over NVLink at T4 compute speed. A faster GPU raises the comm share and so raises
  the cost of the same slow link.

## Does NOT show

- Nothing is measured here; every output is CALCULATED. The measured inputs are T4 step times (one GPU, TP 1), a
  2-GPU PCIe fit (N = 2 only), and a lab Soft-RoCE rate.
- No overlap of communication with compute (upper bound on share); no TP speed-up of compute assumed.
- No H100 compute: pending Modal run D. No 72B compute on any GPU.
- KV-head replication: with TP 4 and 8, Qwen2.5-3B (2 KV heads) must replicate KV heads; that changes memory, not the
  all-reduce bytes above.
- Decode only: prefill all-reduces (message = prompt tokens × hidden) are much larger and are not tabled.
