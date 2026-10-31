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
