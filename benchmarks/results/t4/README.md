# T4 engine track — results

Real GPU measurements of vLLM (and llama.cpp CUDA) on one **free-tier Kaggle Tesla T4**, driven from the
lab machine with [benchmarks/kaggle/run_kaggle.py](../../kaggle/run_kaggle.py). Every number here comes from a
JSONL row in this directory. The rows carry the timestamp, git sha, GPU/driver/CUDA, engine version, model +
revision, every serving flag and the client config. Generated tables: [summary.md](summary.md) (all stages),
[../../kv_capacity_table.md](../../kv_capacity_table.md) (8B KV grid), [RESULTS.md](../../../RESULTS.md) (headline rows).

- [Llama-3.2-3B — the predicted model](#llama-32-3b--the-predicted-model)
- [What ran](#what-ran)
- [Versions](#versions)
- [Task 1 — baseline serve](#task-1--baseline-serve)
- [Predictions vs measured](#predictions-vs-measured)
- [Task 2 — 8B AWQ KV capacity](#task-2--8b-awq-kv-capacity)
- [Task 4 — concurrency sweep](#task-4--concurrency-sweep)
- [Task 5 — quantization](#task-5--quantization)
- [NCCL — 2 × T4 collectives (PCIe, one box)](#nccl--2--t4-collectives-pcie-one-box)
- [Limits — what is emulated or missing](#limits--what-is-emulated-or-missing)
- [Reproduce](#reproduce)

## What ran

One Kaggle kernel version per stage (`make t4-run STAGE=<stage>`). Results are in `<run-id>/results/<stage>/`:

| Stage | Question | Run(s) |
|---|---|---|
| smoke | GPU, driver, packages, DCGM, HF access | 20261014-213711, -214014, -214129; secret diagnosis 20261015-063714; token fix **20261015-064738** |
| baseline | which vLLM serves on sm_75; startup facts; chat API; batch-1 decode; /metrics | 20261014-214232 (failed, see below), **20261014-215653** (Qwen), **20261015-064953** (Llama) |
| kvgrid | 8B AWQ INT4: KV pool vs `--gpu-memory-utilization` × `--max-model-len` | **20261014-220938** |
| sweep | closed loop c=1..64 × two `--max-num-seqs`, open loop, `vllm bench serve` cross-check | Llama **20261015-070248**; Qwen **20261014-220946**; cross-check 20261014-225021 (other session, invalid pair), **20261014-230457** (same session); TTFT-tail diagnosis 20261014-232257, 20261014-233928 |
| quant | FP16 vs AWQ (vLLM) vs GGUF Q8_0/Q4_K_M (llama.cpp CUDA): speed, PPL, lm-eval, cost | **20261014-224513** (speed, PPL), 20261014-230851 (lm-eval vLLM), 20261014-234235 (lm-eval GGUF) |
| nccl | NCCL collectives between the kernel's 2 T4s over PCIe: topology, transport, nccl-tests sweep | smoke 20261016-152535 (wrong NCCL picked, rows split; see below), **20261016-153016** (sweep), **20261016-154427** (P2P follow-up) |

GPU time: **5.41 GPU-hours** of script session time over 23 Kaggle runs pushed by `run_kaggle.py` (5.85 h push→done
upper bound; the three nccl runs are 0.355 h); per run in [runs.jsonl](runs.jsonl) and at the end of [summary.md](summary.md). Not in the ledger: two
versions started from the Kaggle editor on 2026-10-15 (a re-run of the GGUF lm-eval stage, ~24 min, and the
one-minute smoke that proved the secret works from the editor). Kaggle's output download sometimes saves a 502
HTML page in place of a file; `run_kaggle.py` retries and never overwrites a good file with one.

## Versions

Full table with sources: [docs/environment.md](../../../docs/environment.md). Short form: Tesla T4 (sm_75), driver
580.178.04, CUDA 13.0 (driver), Python 3.13.15, **vLLM 0.31.0** with torch 2.13.0+cu130, llama.cpp b11146 CUDA 12.8
prebuilt, lm-eval 0.4.12.

**Models.** `meta-llama/Llama-3.2-3B-Instruct` (revision `0cb88a4f…`) is gated. Until 2026-10-15 the pushed kernels
could not read the `HF_TOKEN` Kaggle secret, so the first round of 3B results (baseline, sweep, quant) is
**`Qwen/Qwen2.5-3B-Instruct` (substitute)**, revision `aa8e7253…`. Llama baseline and sweep followed once the secret
worked; see [the next section](#llama-32-3b--the-predicted-model). Quant stays Qwen-only, since Qwen publishes the
FP16/AWQ/GGUF set from one source. The 8B KV grid uses the ungated `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4`.

Why the secret failed (smoke runs 20261015-063714 and -064738, `secret_diagnosis`): the secret *was* attached. In
versions created by `kaggle kernels push`, `kaggle_secrets` calls
`https://api.kaggle.com/requests/GetUserSecretByLabelRequest`, which answers **HTTP 400**; the client reports that as
*"ConnectionError: Connection error trying to communicate with service"*. A version saved in the Kaggle editor calls
`https://www.kaggle.com/...` and gets **200**. `hf_token()` now retries with `KAGGLE_URL_BASE=https://www.kaggle.com`.
Note: `huggingface_hub.model_info()` *succeeds* on gated repos without a token (metadata only); only a file
download (`config.json`) returns the 401, so the notebook checks both.

## Llama-3.2-3B — the predicted model

`meta-llama/Llama-3.2-3B-Instruct` @ `0cb88a4f…`, FP16, vLLM 0.31.0 (TRITON_ATTN), `--dtype half
--gpu-memory-utilization 0.9 --max-model-len 4096 --no-enable-prefix-caching`.

| Quantity | Predicted | Measured | Source |
|---|---|---|---|
| KV bytes/token | 114,688 | 114,688 = 2 × 28 layers × 8 KV heads × 128 × 2 B | config.json |
| KV pool @ 0.90 | ≈ 55,000 tokens | **53,904** (−2.0 %); check: 5.76 GiB ÷ 114,688 B = 53,926 | baseline 20261015-064953, log + `cache_config_info` |
| GPU blocks × block size | ≈ KV pool | 3,369 × 16 = 53,904 | `cache_config_info` |
| Batch-1 decode | ≤ 50, expect 30–35 tok/s | **36.65** median (35.67–37.11, spread 3.9 %) | baseline 20261015-064953 |
| Weights | — | 6.04 GiB | log |

The decode runs drifted from 37.11 to 35.67 tok/s as the SM clock fell from 1,076 to 773 MHz, with zero throttle-counter time.

**Sweep (run 20261015-070248; this session was power-capped, read the shape, not the absolute values).** The "SW
Power Capping" counter ran for 291 s during the 1-client matched run, and the SM clock averaged 341 MHz at c=1 against
841 MHz at c=64. So the c=1 point (TPOT 102 ms, 12 tok/s) is the clock state, not the engine: c=2 ran at 35 ms ITL.
For clean batch-1 speed use the baseline number above.

| | default `--max-num-seqs` | `--max-num-seqs 8` |
|---|---|---|
| steady output tok/s at c = 8 / 16 / 64 | 157 / 231 / **402** (still rising) | 158 / 159 / 160 (flat) |
| TTFT p50 at c = 16 / 32 / 64 | 378 / 454 / 664 ms | **6,829 / 19,653 / 44,671 ms** |
| vLLM KV usage max at c = 64 | 0.42 (Qwen: 0.13; Llama's tokens cost 3.1× more) | 0.05 |
| preemptions | 0 | 0 |

Open loop at 2.34 / 3.13 / 3.91 req/s (0.75 / 1.0 / 1.25 × the c=64 rate): achieved 2.30 / 2.90 / 3.40 req/s, 0
errors, KV usage up to **0.81**, still 0 preemptions, TTFT p95 0.64 / 0.93 / 1.26 s. Same-session tool cross-check:
TPOT agrees at c=1 (103.9 harness vs 104.0 ms bench) and ITL at c=16 (53.6 vs 54.0 ms). bench's c=16 TTFT p95 is
7.1 s against 1.86 s, the same sampled first-wave stall found with Qwen (bench sends no temperature). Charts:
[throughput](charts/sweep_throughput-llama-3.2-3b-instruct.png), [TTFT](charts/sweep_ttft-llama-3.2-3b-instruct.png),
[ITL](charts/sweep_itl-llama-3.2-3b-instruct.png).

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
runs 21.09 / 11.47 / 10.59 / 16.30 / 18.63, **spread 64 %**, with TTFT steady at 73–82 ms. The identical
measurement in the quant session (run 20261014-224513, same vLLM, same flags) gave **37.16 tok/s, spread 1.0 %**
(37.40 → 37.03), with NVML clocks 964–1,046 MHz and zero throttle-counter time. The baseline session's numbers are
real, but they describe that session's GPU state, not the engine. See *Power capping* under Task 4: a later session
showed the same kind of slowdown together with SW power capping.

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

**Where TTFT is measured** ([observability](../../../observability/README.md#who-measures-ttft)). At c=16 the client TTFT (first streamed chunk, timed from just before the POST)
minus the server's own `time_to_first_token_seconds` mean was **5.4 ms** (`ttft_minus_srv_ttft_ms_mean`, `load-c16`
row): direct to the engine on localhost, HTTP + streaming adds a few ms. A gateway hop would show up in this gap.

## Predictions vs measured

The predictions were logged for Llama-3.2-3B. The measured model is the Qwen2.5-3B substitute, so the KV rows are
restated from Qwen's `config.json`, using the same formula the Llama prediction used:

KV bytes/token = 2 (K,V) × layers × KV heads × head_dim × 2 B = 2 × 36 × 2 × 128 × 2 = **36,864 B/token** (Llama-3.2-3B: 114,688).

| Quantity | Predicted | Measured | Why different |
|---|---|---|---|
| batch-1 decode | ≤ 50 tok/s, expect 30–35 | **37.16** (quant session, spread 1.0 %); 16.3 (baseline session, spread 64 %) | Inside the ceiling, a little above the expected range, for a different model with similar weight bytes (5.79 GiB). The baseline session's low, noisy value matches the power-capped sessions (Task 4 cross-check). |
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
prompt tokens (uuid prefix) **and** `--no-enable-prefix-caching` (both), 128 ± 25 % output tokens, ignore_eos.
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
lists only config groups, and the flags are under `--help=all`. The second attempt (run 20261014-225021) ran in a
different Kaggle session whose T4 averaged **398 MHz SM clock at c=1**, against 873 MHz in the sweep session, so
that pair compared two GPUs, not two tools. The valid cross-check (run **20261014-230457**) runs the harness and
`vllm bench serve` **back to back in one session** on one server, with the identical workload: 256 random prompt
tokens, 128 output, ignore_eos, no jitter, 20 / 64 requests.

| c | tool | TTFT p50 / p95 ms | ITL p50 ms | TPOT p50 ms | output tok/s | SM clock mean |
|---:|---|---:|---:|---:|---:|---:|
| 1 | harness | 110.8 / 124.0 | 40.5 | 40.5 | 23.9 | 500 MHz |
| 1 | vllm bench serve | 116.1 / 142.9 | 45.1 | 44.9 | 21.3 | 461 MHz |
| 16 | harness | 1,215.7 / 1,570.5 | 38.2 | 41.4 | 316.1 | 754 MHz |
| 16 | vllm bench serve | 1,574.6 / **10,510.6** | 38.4 | 39.6 | 234.1 | 762 MHz |

- **Where TTFT is measured.** Both tools time it the same way: clock started just before the HTTP POST,
  stopped at the first SSE chunk carrying `choices` (harness `one_request`; vLLM 0.31.0
  `vllm/benchmarks/lib/endpoint_request_func.py:202–240`). The server's own `vllm:time_to_first_token_seconds` mean
  for the harness runs is 106.7 ms (c=1) and 1,156 ms (c=16), within 5–60 ms of the client numbers. At c=16 that
  server TTFT already includes the time the 16 simultaneous prefills wait for each other.
- **c=1:** the tools agree within ~10 %. The bench run is a little slower and also ran at a lower SM clock (461 vs 500 MHz).
- **c=16:** per-token timing agrees (ITL 38.2 vs 38.4 ms, TPOT 41.4 vs 39.6 ms), but bench's TTFT tail and
  throughput do not. The tail is a cluster: p95 10,510.6 ms ≈ p99 10,512.1 ms, i.e. a few requests waited ~10.5 s
  for their first token. **Root cause not established.** Excluded from the v0.31.0 source: (a) bench's
  `max_concurrent_requests: 32` for `--max-concurrency 16` is a counting artefact, since it buckets requests per
  whole second, so an ending and a starting request both count (`vllm/benchmarks/serve.py:710–723`); the semaphore
  does cap in-flight requests at 16 (`serve.py:980–990`), and `start_time` is taken after the semaphore, so bench
  TTFT excludes client-side waiting. (b) The probe loop is off by default (`probe_request_rate = 0.0`, `serve.py:815`).
  Also seen: bench 0.31.0 no longer sends `temperature=0` (it prints a warning), and it ran no warmup requests,
  while the harness sends 2. bench's GPU-util mean (34 %) is diluted because its sampler window also covers the
  tool's start-up.
- **Diagnosis (run 20261014-232257, `--save-detailed`).** A = the original command on a freshly started server:
  **15 of the first 16 requests** had TTFT 12.46 s, and every later request ≤ 1.6 s. The tail is the **first
  concurrent wave on a cold server**. B = the same plus `--num-warmups 2 --temperature 0`, run on the **same server
  right after A**: no tail (TTFT p95 1,606 ms, 305.8 tok/s, TPOT p50 42.9 ms), in line with the harness (1,571 ms,
  316.1 tok/s, 41.4 ms). Because B's server was already warm, B alone doesn't show that either flag matters.
  **Separating runs (20261014-233928), each on a fresh server:** C = `--num-warmups 2` only: the stall stays (first
  wave 3.7–12.4 s, TTFT p95 12.4 s, 226 tok/s). D = `--temperature 0` only: the stall is gone (first wave
  1.2–2.7 s, p95 2.7 s, 298 tok/s). **The cold first-wave stall comes with the non-greedy sampling path.** bench
  0.31.0 no longer sends `temperature`, so the model's default sampling applies; the harness always sends
  `temperature: 0`. Warmup requests don't prevent it. Hypothesis, not verified: one-time setup of the sampling
  fallback at batch 16 (the startup log says FlashInfer top-p/top-k sampling is unavailable on compute capability
  7.5 and vLLM falls back). The server logs of C/D came back as Kaggle 502 pages, so the stall isn't yet
  matched to log lines.
- **Practical reading:** the harness and `vllm bench serve` agree when both send greedy requests. On this T4 the
  first concurrent wave of *sampled* requests on a fresh server can cost ~12 s TTFT, which matters for
  scale-from-zero ([autoscaling](../../../autoscaling/README.md#scale-from-zero-gapsmd-p6)).
- **Power capping.** In this session NVML's "SW Power Capping" throttle counter grew by 86.4 s during the 107 s
  harness c=1 run and 117.4 s during bench c=1, with the SM clock near 500 MHz. In the quant session the same
  counters stayed at 0 for all 20 decode runs, with clocks at 964–1,231 MHz. **Session-to-session speed differences
  on Kaggle T4s line up with software power capping.** Baseline run 2 (decode spread 64 %) predates the counters,
  so for that run this is consistent but unproven.

## Task 5 — quantization

One session (run **20261014-224513**: no power capping, zero throttle-counter time in every decode run), one model
family, four variants. The vLLM variants use `--dtype half --gpu-memory-utilization 0.9 --max-model-len 4096
--no-enable-prefix-caching`. llama.cpp b11146 uses the CUDA 12.8 prebuilt binary (it ran on sm_75 without a
source build) with `-ngl 99 -c 8192 -np 16 --metrics`. Full table: [summary.md](summary.md#task-5--quantization-speed-quality-cost).

| Variant | Engine | Weights | Batch-1 decode tok/s (5 runs) | c=16 steady tok/s | c=16 TTFT p50 | PPL wikitext-2 | $/1M output tok @ c=16 |
|---|---|---:|---:|---:|---:|---:|---:|
| FP16 | vLLM 0.31.0 | 5.79 GiB | 37.16 (1.0 %) | 341.7 | 196 ms | 8.018 | 0.428 |
| AWQ INT4 | vLLM 0.31.0 | 1.95 GiB | **84.06** (1.9 %) | **536.6** | 144 ms | 8.659 | **0.272** |
| GGUF Q8_0 | llama.cpp b11146 | — | 60.04 (2.2 %) | 284.7 | 245 ms | 8.137 ± 0.215 | 0.513 |
| GGUF Q4_K_M | llama.cpp b11146 | — | 76.61 (2.0 %) | 304.5 | 241 ms | 8.410 ± 0.223 | 0.480 |

- **Decode is memory-bound, as expected:** AWQ INT4 (1.95 GiB of weights) decodes 2.26× faster than FP16 (5.79 GiB).
  On llama.cpp, Q4_K_M is 1.28× faster than Q8_0.
- **Under load the engine matters more than the bits:** at c=16, vLLM AWQ gives 537 tok/s, and llama.cpp Q4_K_M only
  305 tok/s despite similar batch-1 speed. vLLM FP16 (342) beats both GGUF variants at c=16 although it is the
  slowest at batch 1.
- **Quality cost (perplexity):** AWQ +8.0 % over FP16 (8.659 vs 8.018); Q8_0 8.137, Q4_K_M 8.410.
  Method: wikitext-2-raw-v1 test (Salesforce/wikitext; the exact file is
  [20261014-224513_quant/…/wikitext2_test.txt](20261014-224513_quant/results/quant/wikitext2_test.txt), sha256
  `bbf94c53…964574a`, identical in every quant run), 40 non-overlapping 512-token windows, only the second half of
  each window scored (positions 257–511, 10,200 tokens). That is llama-perplexity's own scoring (`first = n_ctx/2`,
  `tools/perplexity/perplexity.cpp:542` at b11146). vLLM is scored through `/v1/completions` with
  `prompt_logprobs`, text tokenized with the HF tokenizer. llama-perplexity tokenizes with the GGUF vocab and prints a
  ± stderr; the vLLM path has no stderr. Cross-engine PPL is close in method, not identical.
- **Cost** = $0.526/h ÷ (c=16 steady tok/s × 3600) × 1e6. Price: Azure `Standard_NC4as_T4_v3` (1× T4, 4 vCPU),
  East US, Linux, on-demand. Source: Azure Retail Prices API, fetched 2026-10-15T01:46Z, raw response in
  [pricing/](pricing/). This is a cloud VM price for this hardware class, not what Kaggle charges (free).
  `benchmarks/cost.py` refuses to run without a cited price.
- **Quality, lm-eval 0.4.12** `local-completions` against each server's `/v1/completions`, `--limit 250` (first
  250 docs; lm-eval itself warns that limit is for testing), default few-shot, **no chat template** (the same for
  all four variants), `tokenized_requests=True`, `num_concurrent=8`. ± is lm-eval's stderr.

  | Variant | gsm8k flexible-extract | gsm8k strict-match | hellaswag acc_norm | hellaswag acc |
  |---|---:|---:|---:|---:|
  | FP16 (vLLM) | 0.656 ± 0.030 | 0.116 ± 0.020 | 0.656 ± 0.030 | 0.536 ± 0.032 |
  | AWQ INT4 (vLLM) | 0.624 ± 0.031 | 0.120 ± 0.021 | 0.628 ± 0.031 | 0.512 ± 0.032 |
  | GGUF Q8_0 (llama.cpp) | 0.692 ± 0.029 | 0.248 ± 0.027 | not supported | not supported |
  | GGUF Q4_K_M (llama.cpp) | 0.676 ± 0.030 | 0.332 ± 0.030 | not supported | not supported |

  - At n=250 every flexible-extract gsm8k score lies within ~1–2 stderr of the others, so this sample size doesn't
    separate the quantizations. Perplexity (above) does, consistently: FP16 < Q8_0 < Q4_K_M < AWQ.
  - strict-match differs by **engine** (vLLM ≈ 0.12, llama.cpp 0.25–0.33) at the same model and similar
    flexible scores. That looks like an output-format/stop-sequence difference between the servers, not a
    quality difference. Unverified; compare `--log_samples` outputs next.
  - **hellaswag on llama.cpp is not possible through this API:** llama-server b11146 `/v1/completions` ignores
    `echo` and returns logprobs only for the generated token (`logprobs.content[]`, no `token_logprobs`), so lm-eval's
    loglikelihood path raises `KeyError('token_logprobs')` (5-doc probe, run 20261014-234235).
  - Runs it took: (1) every variant failed, because the lm-eval venv had no `transformers`; (2) vLLM variants OK,
    llama.cpp variants got HTTP 400 *"request (1434 tokens) exceeds the available context size (512 tokens)"*
    because `-c 8192 -np 16` leaves 512 tokens per slot and gsm8k 5-shot prompts are 1.2–1.6K tokens; (3) llama-server
    restarted for lm-eval with `-c 16384 -np 8` (2,048 per slot). The speed rows above used the `-np 16` server.

## NCCL — 2 × T4 collectives (PCIe, one box)

**What this is:** GPU collective communication between the **two T4s of one Kaggle "GPU T4 x2" VM, over PCIe**.
It is not the scale-out fabric (no NIC, no RDMA, no switch) and not NVLink (T4 has none). Stage `nccl` in
[t4_notebook.py](../../kaggle/t4_notebook.py) records topology and versions, builds nccl-tests, runs the sweep and
parses each run into `nccl.jsonl`: per size time / algbw / busbw / #wrong, plus the transport, channels, graph,
tuning table and per-size algorithm/protocol from `NCCL_DEBUG=INFO` (`NCCL_DEBUG_SUBSYS=INIT,GRAPH,TUNING`, written to
its own file with `NCCL_DEBUG_FILE`; full logs gzipped next to a deduplicated excerpt). Tables: [summary.md](summary.md#nccl--2--t4-collectives-pcie-one-box);
model check against fabric/design/collectives.py: [fabric/design/nccl_check.md](../../../fabric/design/nccl_check.md).

- **Machine shape.** `machine_shape: NvidiaTeslaT4` *is* Kaggle's "GPU T4 x2" (Kaggle/kaggle-api
  `docs/kernels_metadata.md`, main @ `6894864f`: "`NvidiaTeslaT4` for GPU T4 ×2"). Every earlier run in
  runs.jsonl also recorded `gpu_count: 2`. `run_kaggle.py --machine-shape` exists for other shapes (default
  unchanged). The stage exits with code 3 if `nvidia-smi -L` lists fewer than 2 GPUs.
- **Topology.** GPU0 ↔ GPU1 = **PHB**; PCIe **Gen3 x16** under load (Gen1 at idle). CUDA P2P **differed by session**:
  `NS` / torch False in the smoke session, `OK` / True in both measurement sessions.
- **Versions.** NCCL **2.28.9** from a pinned `nvidia-nccl-cu12==2.28.9` installed with `pip --target` into a private
  dir. That is the NCCL the image's torch 2.11.0+cu128 reports. nccl-tests **v2.21.0** (`a3d4589e`, one before the
  latest v2.21.1), `make MPI=0 CUDA_HOME=/usr/local/cuda-12.8 NCCL_HOME=… NVCC_GENCODE=sm_75`; nvcc 12.8.93; driver
  580.178.04. nccl-tests' header confirms `nccl-library=22809`, and the stage stops if it differs.
- **Commands.** `all_reduce_perf -g 2 -b 8 -e 1G -f 2 -n 50 -w 10 -c 1` (the same args for all collectives; the
  Socket contrast uses `-n 10 -w 2`). The 1 GiB busbw of the 3 default repeats spans 0.8 %, so 50 iterations are enough.

| 1 GiB, out-of-place (run 20261016-153016) | busbw GB/s | note |
|---|---:|---|
| all-reduce default ×3 | 3.91 / 3.89 / 3.88 | SHM/direct/direct, Ring/Simple, 2 channels |
| all-reduce `NCCL_ALGO=Ring` / `Tree` | 3.87 / **4.47** | Tree +15 % (P2P follow-up: +14 %), yet NCCL picks Ring |
| all-reduce `NCCL_P2P_DISABLE=1` | 3.86 | same SHM transport: NCCL never used P2P here |
| all-reduce P2P + SHM disabled | 2.25 | NET/Socket (TCP in one VM); 66.5 µs at 8 B |
| all-gather / reduce-scatter / all-to-all / send-recv | 3.19 / 3.60 / 4.43 / 3.64 | algbw 6.38 / 7.20 / 8.85 / 3.64 |
| all-reduce at 8 B (3 repeats) | 16.6 / 18.0 / 18.9 µs | Ring/LL, 1 channel |
| P2P follow-up 20261016-154427: `NCCL_P2P_LEVEL=PHB` vs default | **4.12 vs 3.83** | P2P/direct vs SHM: **1.08×** |

**Why SHM.** NCCL 2.28.9 uses P2P only up to path type PXB by default (`src/graph/paths.cc:319`); the PHB path here is
one level further, so NCCL copies through host shared memory even when CUDA P2P works (`isAllCudaP2p 1` in the
log). Forcing P2P across PHB gains 8 %.

**Smoke failures (20261016-152535), both fixed before the sweep:**
(1) symptom: parsed rows had no size column → evidence: NCCL INFO lines from the in-place call appeared in the middle
of nccl-tests rows in stdout → cause: both write to the same stdout → fix: `NCCL_DEBUG_FILE`. (2) symptom: NCCL
`2.31.2+cuda13.3` in the log and `nccl-library=23102`, while torch reports 2.28.9 → evidence: `pip show -f` lists
`nvidia/nccl/include/nccl.h` under *both* `nvidia-nccl-cu12` 2.28.9 and `nvidia-nccl-cu13` 2.31.2, and a system
`libnccl.so.2.25.1` also exists → cause: the two wheels share one path, and the files on disk are the 2.31.2 copy → fix: the pinned cu12
wheel goes to a private `--target` dir, plus a version assert.

## Limits — what is emulated or missing

- **Free-tier Kaggle T4, single GPU.** The kernel has 2 × T4; the engine stages use only GPU 0 (the `nccl` stage uses both). Sessions land on different
  machines whose clocks differ (398 vs 873 MHz mean SM clock at the same c=1 workload). Results from different
  sessions are not directly comparable; each table says which run it came from.
- **NVML sampling, not DCGM.** DCGM is not installed on Kaggle (no `dcgmi`, `nv-hostengine` or `libdcgm*`), so
  there is no SM_ACTIVE/occupancy, only NVML `util.gpu` (kernel-running time) at 1 Hz.
- **Two 3B models.** Baseline and sweep exist for Llama-3.2-3B (the predicted model) and for Qwen2.5-3B (the earlier
  substitute); quant is Qwen-only. The tables say which model each row is.
- **Closed loop is not real traffic**; the open-loop runs are short (≤ 533 requests) and their rates were
  anchored to the edge of the sweep, not to a measured saturation knee.
- **Single repeat per point** for the sweep. Spread is only measured for batch-1 decode (5 runs).
- **lm-eval at --limit 250, no chat template**: good enough to catch a broken quantization, too small to rank close ones.
- **Benchmark hygiene:** prefix caching is defeated (unique prompts, prefix caching off) and the TTFT cross-check is
  above. The harness only gained open-loop arrivals (`arrival_rate`, `arrival_seed`; closed-loop behaviour unchanged);
  its model of the simulator's load factor was not changed.
- Nothing here is simulated. The k3s vLLM simulator is not involved in any T4 number.

## Reproduce

```bash
make venv && .venv/bin/pip install kaggle==2.2.3 matplotlib==3.11.1   # Kaggle token in ~/.kaggle
make t4-run STAGE=smoke
make t4-run STAGE=baseline
make t4-run STAGE=kvgrid ARGS='--kernel goodput-t4-kv --args "--vllm-version 0.31.0"'
make t4-run STAGE=sweep  ARGS='--args "--vllm-version 0.31.0"'
make t4-run STAGE=quant  ARGS='--args "--vllm-version 0.31.0"'
make t4-run STAGE=nccl   ARGS='--machine-shape NvidiaTeslaT4'                    # add --args=--smoke for probe+build only
make t4-run STAGE=nccl   ARGS='--machine-shape NvidiaTeslaT4 --args="--plan p2pcheck"'
.venv/bin/python benchmarks/analyze.py --price-json benchmarks/results/t4/pricing/azure-NC4as_T4_v3-eastus.json
```

At most 2 GPU kernels run at once (Kaggle: *"Maximum batch GPU session count of 2 reached"*). To continue a stage
that stopped: `ARGS="--resume benchmarks/results/t4/<run-id>"`. Rows already in its JSONL are skipped.
