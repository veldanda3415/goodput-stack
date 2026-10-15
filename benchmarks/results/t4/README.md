# T4 engine track — results

Real GPU measurements of vLLM (and llama.cpp CUDA) on one **free-tier Kaggle Tesla T4**, driven from the
lab machine with [benchmarks/kaggle/run_kaggle.py](../../kaggle/run_kaggle.py). Every number here comes from a
JSONL row in this directory. The rows carry the timestamp, git sha, GPU/driver/CUDA, engine version, model +
revision, every serving flag and the client config. Generated tables: [summary.md](summary.md) (all stages),
[../../kv_capacity_table.md](../../kv_capacity_table.md) (8B KV grid), [RESULTS.md](../../../RESULTS.md) (headline rows).

- [What ran](#what-ran)
- [Versions](#versions)
- [Task 1 — baseline serve](#task-1--baseline-serve)
- [Predictions vs measured](#predictions-vs-measured)
- [Task 2 — 8B AWQ KV capacity](#task-2--8b-awq-kv-capacity)
- [Task 4 — concurrency sweep](#task-4--concurrency-sweep)
- [Task 5 — quantization](#task-5--quantization)
- [Limits — what is emulated or missing](#limits--what-is-emulated-or-missing)
- [Reproduce](#reproduce)

## What ran

One Kaggle kernel version per stage (`make t4-run STAGE=<stage>`). Results are in `<run-id>/results/<stage>/`:

| Stage | Question | Run(s) |
|---|---|---|
| smoke | GPU, driver, packages, DCGM, HF access | 20261014-213711, -214014, -214129 |
| baseline | which vLLM serves on sm_75; startup facts; chat API; batch-1 decode; /metrics | 20261014-214232 (failed, see below), **20261014-215653** |
| kvgrid | 8B AWQ INT4: KV pool vs `--gpu-memory-utilization` × `--max-model-len` | **20261014-220938** |
| sweep | closed loop c=1..64 × two `--max-num-seqs`, open loop, `vllm bench serve` cross-check | **20261014-220946**, bench reruns 20261014-225021, 20261014-230457 |
| quant | FP16 vs AWQ (vLLM) vs GGUF Q8_0/Q4_K_M (llama.cpp CUDA): speed, PPL, lm-eval, cost | see Task 5 |

GPU time: per-run script session time and the push→done upper bound are in [runs.jsonl](runs.jsonl) and at the end of [summary.md](summary.md).

## Versions

Full table with sources: [docs/environment.md](../../../docs/environment.md). Short form: Tesla T4 (sm_75), driver
580.178.04, CUDA 13.0 (driver), Python 3.13.15, **vLLM 0.31.0** with torch 2.13.0+cu130, llama.cpp b11146 CUDA 12.8
prebuilt, lm-eval 0.4.12.

**Models.** `meta-llama/Llama-3.2-3B-Instruct` is gated and the Kaggle kernel had no usable HF token: `kaggle_secrets`
returned *"ConnectionError: Connection error trying to communicate with service"*, which is what Kaggle returns when no
secret is attached to the kernel. So every 3B result is **`Qwen/Qwen2.5-3B-Instruct` (substitute)**, revision
`aa8e7253…`. The 8B KV grid uses the ungated `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4`.
Note: `huggingface_hub.model_info()` *succeeds* on the gated Llama repos without a token (metadata only). Only a
file download (`config.json`) returns the 401, so the notebook checks both.

## Task 1 — baseline serve

**vLLM on sm_75.** The first attempt (run 20261014-214232) failed for **every** version tried (0.31.0, 0.30.0,
0.29.0, 0.28.0), and not because of the GPU. Each install pulled torch 2.13.0+cu130, Kaggle's preinstalled
torchaudio is cu128, and `import vllm` stopped at *"PyTorch and TorchAudio were compiled with different CUDA
versions"*. After the notebook uninstalls torchaudio/torchcodec/torchvision first, **0.31.0 (latest) serves on the T4**
(run 20261014-215653):

- V1 engine, `Using TRITON_ATTN attention backend out of potential backends: ['TRITON_ATTN', 'FLEX_ATTENTION']`
  (FlashAttention isn't offered on sm_75). FlashInfer top-p/top-k sampling: *"unsupported compute capability 7.5; falling back"*.
- torch.compile 23.2 s + piecewise CUDA graph capture. Startup 187.7 s on the first start, including the download.
- `--dtype half --gpu-memory-utilization 0.9 --max-model-len 4096 --no-enable-prefix-caching`.

| Startup fact | Value | Source |
|---|---|---|
| GPU blocks × block size | 10,938 × 16 = **175,008 tokens** | `vllm:cache_config_info` labels `num_gpu_blocks`, `block_size` |
| GPU KV cache size | 175,008 tokens | log `GPU KV cache size:` |
| Available KV memory | 6.01 GiB | log |
| Model weights | 5.79 GiB | log `Model loading took` |
| Max concurrency @ 4096 tokens | 42.73× | log (also `kv_cache_max_concurrency` label) |

Chat API: non-stream `/v1/chat/completions` → 200 with `usage`. Stream with `stream_options.include_usage` →
200, 8 content chunks plus a final usage chunk (`completion_tokens` 9: the EOS token produces no text).

**Batch-1 decode** (5 streamed chat runs, same prompt, 256 tokens, ignore_eos, temperature 0): **median 16.30 tok/s**,
runs 21.09 / 11.47 / 10.59 / 16.30 / 18.63, **spread 64 %**. TTFT was steady at 73–82 ms. Treat this as a range,
not a number. The c=1 point of the sweep (other session, `/v1/completions`, 128 ± 25 % tokens) measured TPOT
p50 27.3 ms, i.e. 36.6 tok/s per request. Hypothesis for the spread: GPU clock behaviour that differs between Kaggle
sessions and over time (see the cross-check below, where one session ran at less than half the SM clock of
another). Batch-1 decode runs now record NVML samples and throttle-reason counters; the quant stage repeats the FP16 decode with them.

**/metrics names** (from the `# TYPE` lines of the idle scrape, [metric-names.json](20261014-215653_baseline/results/baseline/logs/metric-names.json)):

| Role | vLLM 0.31.0 metric |
|---|---|
| TTFT | `vllm:time_to_first_token_seconds` (histogram) |
| ITL | `vllm:inter_token_latency_seconds` (histogram); per-request TPOT: `vllm:request_time_per_output_token_seconds` (histogram) |
| queue (waiting) | `vllm:num_requests_waiting` (gauge), `vllm:num_requests_waiting_by_reason` (gauge); queue time `vllm:request_queue_time_seconds` |
| running | `vllm:num_requests_running` (gauge) |
| KV usage | `vllm:kv_cache_usage_perc` (gauge, 0–1) |
| preemptions | `vllm:num_preemptions_total` (counter), `vllm:request_num_preemptions` (histogram) |

Raw scrapes: [idle](20261014-215653_baseline/results/baseline/logs/metrics-idle.txt),
[under c=16 load](20261014-215653_baseline/results/baseline/logs/metrics-load.txt) (running 16, waiting 0,
KV 0.030), [after](20261014-215653_baseline/results/baseline/logs/metrics-after.txt).

**Where TTFT is measured (#3).** At c=16 the client TTFT (first streamed chunk, timed from just before the POST)
minus the server's own `time_to_first_token_seconds` mean was **5.4 ms** (`ttft_minus_srv_ttft_ms_mean`, `load-c16`
row): direct to the engine on localhost, HTTP + streaming adds a few ms. A gateway hop would show up in this gap.

## Predictions vs measured

The predictions were logged for Llama-3.2-3B. The measured model is the Qwen2.5-3B substitute, so the KV rows are
restated from Qwen's `config.json`, using the same formula the Llama prediction used:

KV bytes/token = 2 (K,V) × layers × KV heads × head_dim × 2 B = 2 × 36 × 2 × 128 × 2 = **36,864 B/token** (Llama-3.2-3B: 114,688).

| Quantity | Predicted | Measured | Why different |
|---|---|---|---|
| batch-1 decode | ≤ 50 tok/s, expect 30–35 | 16.3 median (10.6–21.1) chat; 36.6 per-request at c=1 in the sweep session | Under the ceiling either way. Session-to-session GPU clock differences, not the engine, dominate the spread (see cross-check). Different model, with similar weight bytes (5.79 GiB measured). |
| KV pool @ 0.90 | ≈ 55K tokens for Llama → **171,111** restated (same KV bytes ÷ 36,864) | **175,008** (log and `cache_config_info`) | +2.3 %: the KV memory left over (6.01 GiB measured) is a bit more than the prediction assumed. The model's GQA (2 KV heads) makes each token 3.1× cheaper than Llama-3.2-3B. |
| GPU blocks × block size ≈ KV pool | equal | 10,938 × 16 = 175,008 = KV pool | as predicted |

## Task 2 — 8B AWQ KV capacity

`hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4` @ `db1f81ad…`, vLLM 0.31.0. **All 12 cells started.** Table:
[kv_capacity_table.md](../../kv_capacity_table.md). The KV pool depends only on `--gpu-memory-utilization`:
**37,744 / 56,224 / 62,192 tokens** at 0.80 / 0.90 / 0.95 (2,359 / 3,514 / 3,887 blocks of 16), at every
`--max-model-len`. Weights take 5.39 GiB. The maximum number of concurrent full-length sequences comes from vLLM's
own log line (`Maximum concurrency for N tokens per request`): from **30.37×** (0.95, 2048) down to **2.30×**
(0.80, 16384). The `config.json` check (131,072 B/token) reproduces each pool to within the GiB rounding.

## Task 4 — concurrency sweep

Qwen2.5-3B FP16, vLLM 0.31.0, the harness (`benchmarks/harness`, `/v1/completions` streamed), 256 unique random
prompt tokens (uuid prefix) **and** `--no-enable-prefix-caching` (#1: both), 128 ± 25 % output tokens, ignore_eos.
Full table and charts: [summary.md](summary.md#task-4--concurrency-sweep).

| | default `--max-num-seqs` | `--max-num-seqs 8` |
|---|---|---|
| steady output tok/s at c = 1 / 8 / 16 / 64 | 35 / 209 / 338 / **615** | 32 / 209 / 211 / 209 |
| TTFT p50 at c = 16 / 32 / 64 | 196 / 303 / 469 ms | **5,070 / 14,867 / 34,381 ms** |
| ITL p50 at c = 64 | 64.6 ms | 33.0 ms |
| vLLM waiting max at c = 64 | 36 | 56 |
| preemptions | 0 everywhere | 0 everywhere |

- With the default scheduler, throughput is **still rising at c=64** (615 tok/s, KV usage ≤ 13 %). There is no
  knee inside c ≤ 64, so the "knee" rule (smallest c with ≥ 90 % of max) lands on the sweep's edge, c=64,
  4.75 req/s. The open-loop rates 3.56 / 4.75 / 5.93 req/s are therefore *around the sweep's edge*, not around a
  saturation point. The server kept up with all three (achieved 3.44 / 4.58 / 5.54 req/s, 0 errors, running up to
  162, TTFT p95 0.45 / 0.69 / 1.04 s, ITL p50 52 / 65 / 115 ms).
- `--max-num-seqs 8` caps the batch: throughput is flat at ~210 tok/s from c=8, and everything above 8 waits in
  the queue. ITL stays at 33 ms while TTFT grows by ~1 s per extra client. That is the scheduler trade-off in one
  chart: per-user decode speed vs queueing delay.
- The default `--max-num-seqs` is printed as `None` in `vllm serve --help=all` ("set in
  EngineArgs.create_engine_config"). Its resolved value was not in the log or `/metrics`; the open-loop run
  reached 162 running requests, so it is **≥ 162**.
- NVML: `util.gpu` 92–98 % at every point, including c=1. This is the "a kernel was running" signal, not SM
  occupancy (see [benchmarks/README.md](../../README.md#t4-engine-track-kaggle)). Power 65–67 W of the 70 W cap,
  SM clock mean 700–1,016 MHz (max 1,590), 77–81 °C.

**Cross-check with `vllm bench serve`.** Its first attempt failed on flag discovery: `vllm bench serve --help`
lists only config groups, and the flags are under `--help=all`. The second attempt (run 20261014-225021) worked
but ran in a different Kaggle session. Its T4 averaged **398 MHz SM clock at c=1** against 873 MHz in the sweep
session, and it measured 14.8 tok/s / TPOT p50 66 ms against the harness's 35.4 / 27.3 ms. That pair compares two
GPUs' clocks, not two tools, so the cross-check was re-run with the harness and `vllm bench serve` back to back in
**one** session at the identical workload (run 20261014-230457): results in [summary.md](summary.md#cross-check-harness-vs-vllm-bench-serve-same-server-default-max-num-seqs).
Both tools measure TTFT the same way (clock started just before the POST, stopped at the first SSE chunk with
`choices`; vLLM 0.31.0 `vllm/benchmarks/lib/endpoint_request_func.py:202–240`).

## Task 5 — quantization

(see summary.md; filled in below once the quant run is in)

## Limits — what is emulated or missing

- **Free-tier Kaggle T4, single GPU.** The kernel has 2 × T4; only GPU 0 is used. Sessions land on different
  machines whose clocks differ (398 vs 873 MHz mean SM clock at the same c=1 workload). Results from different
  sessions are not directly comparable; each table says which run it came from.
- **NVML sampling, not DCGM.** DCGM is not installed on Kaggle (no `dcgmi`, `nv-hostengine` or `libdcgm*`), so
  there is no SM_ACTIVE/occupancy, only NVML `util.gpu` (kernel-running time) at 1 Hz.
- **Substitute model.** Every 3B number is Qwen2.5-3B-Instruct, not Llama-3.2-3B (gated, no token in the kernel).
- **Closed loop is not real traffic**; the open-loop runs are short (≤ 533 requests) and their rates were
  anchored to the edge of the sweep, not to a measured saturation knee.
- **Single repeat per point** for the sweep. Spread is only measured for batch-1 decode (5 runs).
- Nothing here is simulated. The k3s vLLM simulator is not involved in any T4 number.

## Reproduce

```bash
make venv && .venv/bin/pip install kaggle==2.2.3 matplotlib==3.11.1   # Kaggle token in ~/.kaggle
make t4-run STAGE=smoke
make t4-run STAGE=baseline
make t4-run STAGE=kvgrid ARGS='--kernel goodput-t4-kv --args "--vllm-version 0.31.0"'
make t4-run STAGE=sweep  ARGS='--args "--vllm-version 0.31.0"'
make t4-run STAGE=quant  ARGS='--args "--vllm-version 0.31.0"'
.venv/bin/python benchmarks/analyze.py --price-json benchmarks/results/t4/pricing/azure-NC4as_T4_v3-eastus.json
```

At most 2 GPU kernels run at once (Kaggle: *"Maximum batch GPU session count of 2 reached"*). To continue a stage
that stopped: `ARGS="--resume benchmarks/results/t4/<run-id>"`. Rows already in its JSONL are skipped.
