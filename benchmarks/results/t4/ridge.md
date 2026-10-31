# Ridge point and engine ceiling — Qwen2.5-3B FP16 on one T4 (Kaggle T4, real)

Part A of the T4 ridge work. Question: where does output stop growing as users are added on one T4, and why did
the earlier HTTP sweep reach only 615 output tok/s at 64 users?

Every measured number below comes from a JSONL row or a raw file in this directory, with the command that made it.
Numbers marked CALCULATED are arithmetic, not measurements.

## Task 0 — answers from data we already have (no GPU)

Source: run **20261014-220946_sweep** (`sweep.jsonl`, `mnsdefault-c64/` and `mns8-c64/` raw files, `logs/server-mnsdefault.log`).
Commands: Python over `requests.jsonl`, `gpu.csv` and `metrics.jsonl`, restricted to the measured window
(first request sent → last request finished); `grep` over the server log for the `loggers.py` throughput lines in that window.

1. **Exact workload of both sweeps** (identical client config, `client` field of every row):
   `/v1/completions`, streamed, **prompt 256 tokens** (`usage.prompt_tokens` = 256 on all 256 requests at c=64;
   unique random filler words with a uuid prefix, fitted with `/tokenize`), **output `max_tokens` 128 ± 25 %**
   (`max_tokens_jitter` 0.25 → uniform 96–160, measured mean 128.17), **ignore_eos true**, temperature 0,
   **start jitter 1.0 s** per worker (0 at c=1), requests = max(20, 4 × c) (256 at c=64), 2 sequential warm-up requests.
   Server: `--dtype half --gpu-memory-utilization 0.9 --max-model-len 4096 --no-enable-prefix-caching`; the second
   sweep adds `--max-num-seqs 8`. So the old sweep was **2:1 prompt-heavy** (256 in / 128 out), not 128 in / 256 out.
2. **Same session: yes.** Both sweeps are rows of one stage run (`run_id` 20261014-220946_sweep, git f03cd60, one Kaggle
   kernel version, script session 2,064.3 s). Default-scheduler c=64 ran 02:25:53–02:26:48 UTC, `--max-num-seqs 8`
   c=64 ran 02:40:48–02:43:27 UTC, same server restart in between. SM clock in-window mean 996 MHz vs 1,030 MHz.
3. **64-user default point** (in the measured window, 54 NVML samples at 1 Hz, 53 /metrics samples):

   | quantity | value |
   |---|---|
   | NVML util.gpu mean / p50 | **100.0 % / 100 %** (min 100) |
   | SM clock mean / p50 (min–max) | **996 / 990 MHz** (795–1,110) |
   | power mean / p50 (max) | **66.4 / 66.4 W** (73.6) of the 70 W cap |
   | vLLM running mean / p50 / max | 57.8 / 63 / 64 |
   | vLLM waiting mean / max | 1.5 / 36 |
   | KV usage mean / max | 0.107 / 0.129 |
   | preemptions (`num_preemptions_total` delta) | **0** |
   | steady output tok/s (harness) | 615.46 |
   | ITL p50 / p95, TPOT p50 | 64.6 / 208.4 ms, 95.5 ms |

   Server log throughput lines in the window (`loggers.py:320`, 10 s averages, UTC):

   | time | prompt tok/s | generation tok/s | running | KV |
   |---|---:|---:|---:|---:|
   | 02:25:59 | 1,663.3 | 84.9 | 64 | 10.0 % |
   | 02:26:09 | 793.4 | 780.8 | 61 | 11.9 % |
   | 02:26:19 | 1,151.9 | 669.0 | 64 | 12.7 % |
   | 02:26:29 | 1,356.8 | 603.8 | 64 | 12.2 % |
   | 02:26:39 | 1,432.8 | 602.9 | 63 | 11.4 % |

   Resolved default `--max-num-seqs` for these serve flags: **256**, `max_num_batched_tokens` **2048**, chunked prefill on
   (run 20261022-221119_p8x2 `engine-config` row: `EngineArgs.create_engine_config(OPENAI_API_SERVER).scheduler_config`,
   same model, `--max-model-len 8192`). The 2026-10-14 sweep itself only showed it is ≥ 64.
4. **Verdict (from existing data).** At 64 users the GPU looked **busy, not idle-waiting**: NVML util.gpu was 100 % in
   every sample of the window, power sat at 66 W of the 70 W cap and the SM clock averaged ~1 GHz, well below the
   1,590 MHz max, i.e. power-limited, not idle. The server was nearly full (running p50 63 of 64, waiting ≈ 0), so the
   client kept it fed. The engine was doing **two jobs**: the log shows ~1,150–1,430 prompt tok/s next to ~600 output
   tok/s, because every 256-token prompt is prefilled while 128 tokens come out (chunked prefill mixes them into the
   decode steps: ITL p95 208 ms vs p50 65 ms). util.gpu = 100 % only says a kernel was running, not how full the SMs
   were (NVML, not DCGM), and client CPU was **not recorded**, so a client limit cannot be excluded from this data alone;
   it is unlikely given the server held ~63 running requests. Nothing in this data says the T4 hit a ceiling: KV
   usage was 13 % and throughput was still rising from c=32 (461) to c=64 (615).

## Predictions (written before Task 2, verbatim from the assignment)

Setup: Qwen/Qwen2.5-3B-Instruct @ aa8e7253 FP16, `--dtype half --gpu-memory-utilization 0.95`, prefix caching OFF, everything else default; prompt 128 tokens, output 256 tokens fixed (ignore_eos), temperature 0.
- KV cache at 0.95 ≈ 197,000 tokens (175,008 at 0.90 + ≈ 0.75 GiB ÷ 36,864 B). CALCULATED.
- Ridge (datasheet: 65 TFLOPS FP16, 300 GB/s → ≈ 217 ops/byte; weights 6.22 GB; ≈ 6.2 GFLOP/token; average context ≈ 256 tokens) ≈ 330 sequences. CALCULATED.
- Output-token ceiling at the ridge ≈ 7,000 tok/s (10,500 tok/s compute ceiling × 256/384, since prompts take a third of the compute). CALCULATED, datasheet peaks.
- Expected measured: 2,000–4,000 output tok/s offline at max-num-seqs 384, flattening between 150 and 250 sequences; HTTP run at 384 users clearly below the offline number; SM clock may drop under full load (70 W card).

Task 4 prediction (written before Task 4): KV full at ≈ 48 sequences (197,000 ÷ 4,096), preemptions appear, throughput well below Task 2.

## Decisions made

- **One warm-up per point, inside the benchmark.** Each offline point runs `--num-warmups 32` (32 warm-up prompts
  processed and discarded by the tool before its timed run) instead of a separate discarded run. That saves one engine
  start (~1.5–3 min of GPU time) per point.
- **Temperature is 1.0 offline, not 0.** `vllm bench throughput` 0.31.0 hard-codes `SamplingParams(temperature=1.0,
  top_p=1.0, ignore_eos=True)` (`vllm/benchmarks/throughput.py`, `_run_vllm_requests`), and `vllm bench throughput
  --help=all` lists no temperature flag. Output length is fixed by ignore_eos, so token counts are unaffected; the
  sampling kernel differs from greedy.
- **Engine metrics offline.** The offline tool has no /metrics endpoint, so
  [offline_throughput.py](../../kaggle/offline_throughput.py) calls the same `add_cli_args` + `main` that
  `vllm bench throughput` calls and reads the in-process Prometheus registry at 1 Hz
  (`vllm.v1.metrics.reader.get_metrics_snapshot`). Preemptions = delta of `vllm:num_preemptions` over the timed window.
- **Timed window** = [end − the tool's own `elapsed_time`, end]. NVML, CPU and engine-metric means are over that window only.
- **Point order 64 → 384, budget guard 0.45 h.** HTTP (Task 3), the 512 point and Task 4 were set to start only with ≥ 0.10 /
  0.07 / 0.06 h of the part budget left.
- **Everything else default**, as the setup says. That includes `--max-model-len` (32,768 from the model config) and
  `--max-num-batched-tokens`, which vLLM resolves differently per entry point (next section).

## Task 2 — offline engine ceiling (run 20261031-082141_ridge, Kaggle T4, real)

One Kaggle session (script session 1,410 s = **0.392 GPU-h**), GPU 0 only, git `e2f06c1`, Tesla T4, driver 580.178.04,
CUDA 13.0 (driver), vLLM 0.31.0 (torch 2.13.0+cu130, installed with uv in 117 s), `Qwen/Qwen2.5-3B-Instruct` @
`aa8e72537993ba99e69dfaafa59ed015b17504d1`, 4 vCPUs (2 physical cores), 31.3 GiB RAM. Command per point (flags checked
against `vllm bench throughput --help=all`, [logs/vllm-bench-throughput-help.txt](20261031-082141_ridge/results/ridge/logs/vllm-bench-throughput-help.txt)):

```
vllm bench throughput --backend vllm --model Qwen/Qwen2.5-3B-Instruct --revision aa8e72537993ba99e69dfaafa59ed015b17504d1 \
  --dtype half --gpu-memory-utilization 0.95 --no-enable-prefix-caching --max-num-seqs N --dataset-name random \
  --random-input-len 128 --random-output-len 256 --random-range-ratio 0.0 --num-prompts 4N --num-warmups 32 --seed 0 --output-json ...
```

Scheduler config vLLM resolves for these flags (`EngineArgs.create_engine_config(UsageContext.X).scheduler_config`,
in-session, `sched-*` rows): offline `LLM_CLASS` → **max_num_batched_tokens 8,192**; `vllm serve` (`OPENAI_API_SERVER`)
→ **2,048**. Both: max_num_seqs 384 at `--max-num-seqs 384`, chunked prefill on, max_model_len 32,768. The offline
log confirms 8,192 at every point.

| max-num-seqs | prompts | **output tok/s** | total tok/s | req/s | KV pool (log) | preemptions | running mean | waiting mean | KV usage mean / max | SM clock mean (p50) MHz | power mean W | util.gpu mean % | system CPU % (4 vCPUs) | elapsed s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 64 | 256 | **941.5** | 1,412.2 | 3.68 | 205,712 | 0 | 62.1 | 92.4 | 0.078 / 0.119 | 1,067 (1,088) | 66.4 | 97.1 | 4.5 | 69.6 |
| 128 | 512 | **1,265.1** | 1,897.7 | 4.94 | 201,904 | 0 | 120.8 | 187.3 | 0.152 / 0.243 | 1,011 (1,035) | 66.3 | 98.1 | 4.0 | 103.6 |
| 256 | 1,024 | **1,421.2** | 2,131.8 | 5.55 | 194,848 | 0 | 242.0 | 391.8 | 0.319 / 0.505 | 975 (1,005) | 65.5 | 99.6 | 3.4 | 184.5 |
| 384 | 1,536 | **1,458.6** | 2,187.9 | 5.70 | 192,112 | 0 | 364.5 | 595.6 | 0.491 / 0.768 | 967 (1,020) | 65.3 | 99.6 | 3.3 | 269.6 |

Output and total tok/s, req/s, elapsed: the tool's own `Throughput:` line and `--output-json`. KV pool: log
`GPU KV cache size:`. Running/waiting/KV/preemptions: engine registry in the timed window. NVML at 1 Hz (`gpu_sampler`),
CPU with psutil at 1 Hz. Model weights 5.79 GiB (log), available KV memory 7.06 → 6.60 GiB as max-num-seqs grows
(CUDA-graph and activation memory take the rest). NVML "SW Power Capping" counter: 0 / 0.7 / 1.9 / 4.6 s over the
four runs. Chart: [charts/ridge_output_vs_max_num_seqs.png](charts/ridge_output_vs_max_num_seqs.png).

- **Where it flattens.** +34 % from 64 → 128, +12 % from 128 → 256, **+2.6 % from 256 → 384**. The ridge for this
  workload on this card is reached at about **256 sequences, ≈ 1,420–1,460 output tok/s (≈ 2,130–2,190 total tok/s)**.
  The 512 point was not run: its rule needs > 5 % growth at 384 (it was 2.6 %), and the budget had 0.058 h left.
- **The GPU is saturated, the CPU is not.** util.gpu 97–100 %, power 65–66 W of the 70 W cap at every point, and the SM
  clock **falls as the batch grows** (1,067 → 967 MHz mean; max 1,590). The whole 4-vCPU VM was 3–4.5 % busy during the timed runs.
- **Memory is not the limit.** KV usage peaked at 0.77 at 384 with 0 preemptions; the batch was always full (running ≈
  max-num-seqs, hundreds waiting).
- CALCULATED from the table: time per engine step ≈ running ÷ output tok/s = 66 ms at 64, 95 ms at 128, 170 ms at 256,
  250 ms at 384.

## Task 3 — HTTP at 384 users: NOT RUN

The budget guard skipped it: after the four offline points the session was at 0.392 h of the 0.45 h Part A budget, and
the rule needed ≥ 0.10 h for a server start plus two load runs (row `http`, reason `budget: session 0.392 h`). The code
(`http_run`: 1 and 4 harness processes, client/server CPU, full-batch server-counter window) is tested locally and
ready. Next step: `make t4-run STAGE=ridge ARGS='--args "--mns 384 --extra-mns 0 --parts http --budget-h 0.2"'`
would have run it; see the overall summary for whether there was budget left at the end.

## Task 4 — memory-limited case: NOT RUN

Skipped by the same guard (row `memlimit-in3840-mns64`, `budget: session 0.392 h of 0.45`). The prediction above stays untested.

## Why the earlier HTTP sweep reached only 615 output tok/s at 64 users

**Limited by the GPU at a batch of 64 with a prompt-heavy mix, not by the client or the CPU.** Evidence:

1. The engine alone, with no HTTP and no client, at max-num-seqs 64 makes 941.5 output tok/s on a 128-in/256-out mix,
   with util.gpu 97 %, 66 W and ~1.07 GHz. The step time is ~66 ms CALCULATED, the same as the old HTTP run's ITL p50
   at c=64 (64.6 ms). Per decode step, HTTP and offline cost the same.
2. The old run's mix was 256 in / 128 out, i.e. 4× the prompt tokens per output token. Its server log shows ~1,150–1,430
   prompt tok/s next to ~600–670 generation tok/s, **≈ 1,800–2,050 total tok/s**: *more* total tokens/s than the
   offline engine processed at batch 64 (1,412). The HTTP server was not starved; prefill took a large share of the steps.
3. The old server held 63 of 64 requests running (p50), waiting ≈ 0, util.gpu 100 %, power at the cap (Task 0).
4. More users would have raised output: the engine ceiling for this card is ~1,460 output tok/s at 256–384 sequences.
   615 was a point on the rising part of the curve (c=32 → 64 was still +33 %), not a ceiling.

What is **not** shown: a same-session HTTP-vs-offline comparison and client CPU under HTTP load (Task 3 did not run).
The old run's client CPU was never recorded. So "not the client" rests on 1–3: equal step times and a server that was
full and busy. It is not a direct CPU measurement.

## Predicted vs measured

| Prediction | Predicted | Measured | Verdict / why |
|---|---|---|---|
| KV cache at 0.95 | ≈ 197,000 tokens CALCULATED | **205,712 / 201,904 / 194,848 / 192,112** at max-num-seqs 64/128/256/384 | within −2.5 % … +4.4 %; the pool shrinks as max-num-seqs grows (CUDA graphs and activation memory are sized by the batch) |
| Ridge | ≈ 330 sequences CALCULATED | flattening between 256 and 384 (+2.6 %) | same order; the measured knee is at ~256 |
| Output-token ceiling at the ridge | ≈ 7,000 tok/s CALCULATED, datasheet peaks | **1,458.6** at 384 | 21 % of the datasheet-based ceiling. The card runs at ~0.97–1.07 GHz under load (power cap 70 W), not the 1.59 GHz the 65 TFLOPS assumes (×0.61). The rest of the gap (Triton attention on sm_75, no FlashAttention, sampling, scheduling) is not separated by this data |
| Offline at 384 | 2,000–4,000 output tok/s | **1,458.6** | below the range |
| Flattening | between 150 and 250 sequences | between 256 and 384 (12 % gain 128→256, 2.6 % 256→384) | later than predicted |
| HTTP at 384 clearly below offline | — | not measured (Task 3 skipped) | untested |
| SM clock drops under full load | may drop | **yes**: mean 1,067 → 967 MHz as the batch grows 64 → 384; power 65–66 W of 70; "SW Power Capping" counter 0 → 4.6 s | as predicted |
| Task 4: KV full at ≈ 48 sequences, preemptions, throughput well below Task 2 | — | not measured | untested |

## Does NOT show

- One T4, one Kaggle session, one model (Qwen2.5-3B-Instruct), FP16 only, one length mix (128 in / 256 out).
- NVML util.gpu (a kernel was running), not DCGM SM activity/occupancy; DCGM is not available on Kaggle.
- The ceiling line uses datasheet peaks (65 TFLOPS FP16, 300 GB/s), not a measured roofline of this card.
- Offline sampling is temperature 1.0 (hard-coded in the tool). The HTTP comparison and the memory-limited case did not run.
- One repeat per point; no spread.

## F2 — memory-limited case (follow-up)

### Predictions (written before the F2 run, verbatim from the assignment)

KV pool at 0.95 ≈ 192,000–206,000 tokens (Build 14); with input 3,840 / output 256 each sequence needs up to 4,096 tokens → KV full at ≈ 47–50 sequences (CALCULATED); at max-num-seqs 64, preemptions appear and output tok/s falls well below the short-context 941.5 at 64; at 32 no preemptions.

### Decisions made

- **Same Kaggle session as F1** (run 20261031-171557_followup). This saves one vLLM install. F2's 0.15 h budget is
  measured from F2's own start. The install counts against F1.
- **Point order 64, 32, 48.** 64 is the point the prediction is about (preemptions), so it ran first. A later point
  needed ≥ 0.03 h of the F2 budget left.
- **num-prompts = max-num-seqs** (one full batch, 64 prompts at 64), and `--num-warmups 2`. This was chosen for
  budget: each 3,840-token prompt is long to prefill. Build 14's short-context points used 4 × max-num-seqs prompts.
- Flags are as in Build 14 (`vllm bench throughput … --dtype half --gpu-memory-utilization 0.95
  --no-enable-prefix-caching --random-range-ratio 0.0 --seed 0`), plus `--max-num-batched-tokens 8192`. That flag is
  listed in `vllm bench throughput --help=all`, and the offline log confirms 8,192. Preemptions = the delta of the
  engine counter `vllm:num_preemptions` over the timed window (in-process registry, 1 Hz). Sampling is temperature
  1.0, hard-coded in the tool.

### Run (20261031-171557_followup, Kaggle T4, real)

- Git `0593862`, Tesla T4 (GPU 0), driver 580.178.04, CUDA 13.0, vLLM 0.31.0, torch 2.13.0+cu130.
  `Qwen/Qwen2.5-3B-Instruct` @ `aa8e72537993ba99e69dfaafa59ed015b17504d1`. F2 used **0.134 GPU-h** (marks `f2-begin`
  → `f2-end`).
- Command:

  ```
  vllm bench throughput --backend vllm --model Qwen/Qwen2.5-3B-Instruct --revision aa8e72537993ba99e69dfaafa59ed015b17504d1 \
    --dtype half --gpu-memory-utilization 0.95 --no-enable-prefix-caching --max-num-seqs 64 --dataset-name random \
    --random-input-len 3840 --random-output-len 256 --random-range-ratio 0.0 --num-prompts 64 --num-warmups 2 --seed 0 \
    --max-num-batched-tokens 8192 --output-json ...
  ```

- Raw data: row `f2-in3840-mns64` in
  [followup.jsonl](20261031-171557_followup/results/followup/followup.jsonl), the log
  [logs/f2-in3840-mns64.log](20261031-171557_followup/results/followup/logs/f2-in3840-mns64.log), and the
  `f2-in3840-mns64.{bench.json, engine-metrics.json, gpu.csv, cpu.csv}` files.

| max-num-seqs | prompts | **output tok/s** | total tok/s | KV pool (log) | running max / mean | waiting mean | KV usage mean / **max** | **preemptions** | SM clock mean (p50) MHz | power mean W | util.gpu mean % | elapsed s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **64** | 64 | **47.09** | 753.41 | 205,712 | **53** / 34.4 | 23.7 | 0.652 / **0.9999** | **3** | 1,281 (1,335) | 65.9 | 99.4 | 347.9 |
| 32 | — | not run (F2 budget: 0.016 h left) | | | | | | | | | | |
| 48 | — | not run (same) | | | | | | | | | | |

What happened at 64 (engine log `loggers.py` lines, 10–17 s averages, and the 1 Hz registry):

- **Prefill was slow and it starved decode.**
  - The engine admitted ~4 new 3,840-token prompts every 17 s, at **~870–1,100 prompt tok/s**.
  - The requests already running made only 1–6 output tok/s together during that phase.
  - CALCULATED: one 8,192-token chunked-prefill step ≈ 8,192 ÷ ~900 tok/s ≈ 9 s. Every running sequence got one token
    per such step.
- **The KV pool filled at 53 sequences.** KV usage rose to 99.5 % with 53 running and 11 waiting at 21:35:13. Then
  decode ran alone at ~220–230 output tok/s with 50–52 running.
- **3 preemptions,** at +219 s, +235 s and +253 s of the timed window. At those points 52 / 51 / 50 were running,
  12–14 waiting, KV 98 %.
- The leftover prompts were prefilled after that (~930 prompt tok/s again), and the last 11–13 sequences decoded at
  ~150–170 tok/s.
- Over the whole run: 245,760 prompt + 16,384 output tokens in 348 s.
- The SM clock averaged 1.28 GHz, higher than the short-context runs (~1.0 GHz), at the same 66 W.

### Predicted vs measured (F2)

| Prediction | Measured | Verdict |
|---|---|---|
| KV pool at 0.95 ≈ 192,000–206,000 tokens | **205,712** (log, max-num-seqs 64) | inside the range |
| KV full at ≈ 47–50 sequences (CALCULATED: pool ÷ 4,096) | KV reached 99.5–99.99 % with **53** running (205,712 ÷ 4,096 = 50.2 CALCULATED) | close. Running sequences in decode hold less than 4,096 tokens (prompt + tokens so far), so 53 fitted |
| at max-num-seqs 64, preemptions appear | **3** preemptions | as predicted |
| output tok/s well below the short-context 941.5 at 64 | **47.09** (5 % of 941.5); total 753.4 vs 1,412.2 | as predicted. The prompt is 15× longer per output token (3,840 / 256), and prefill ran at only ~900 tok/s |
| at 32: no preemptions | not run (F2 budget) | untested |

### Does NOT show (F2)

- Only the 64 point ran. Where preemption starts between 32 and 64 is **not measured**: the 32 and 48 points did not
  run. So whether 48 already preempts is unknown.
- One full batch of 64 prompts (num-prompts = max-num-seqs), not a steady state with a queue behind it. Output tok/s
  includes the long prefill-only ramp.
- Why prefill at 3,840 tokens runs at ~900 tok/s on this card is not separated (attention backend, chunk size, clock).
  The only measured facts are the rates above.
- One run, one session, temperature 1.0 (offline tool).
