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
- **No MPS fallback.** If the MPS daemon cannot start, record the exact error and skip; nothing else replaces it.
- **Budget guard 0.30 h**, with each step's start conditional on the time left (MPS needed ≥ 0.07 h). The cheap 0.5B model's
  startup for Part C (weight size and KV pool) runs last, in this session, because the Part C memory fractions have to be
  computed from measured weight sizes before Part C runs.
- **Load tool:** the repo harness for every condition, one spawned client process per loaded instance. 3 requests per
  user (96 at 32 users, 48 per instance at 16). Output tok/s = delta of `vllm:generation_tokens_total` over the **joint
  window**, the /metrics samples where every loaded instance had ≥ 0.9 × its users running. The harness's own
  steady-window number is shown next to it.

## Results (run 20261031-085014_twoinst, Kaggle T4, real)

One session, script session 1,018 s = **0.283 GPU-h** (uv install took 319 s this time). git `7290550`, Tesla T4 (GPU 0
only), driver 580.178.04, CUDA 13.0, vLLM 0.31.0 (torch 2.13.0+cu130), `Qwen/Qwen2.5-3B-Instruct-AWQ` @ `3559b226…`,
flags `--dtype half --no-enable-prefix-caching --revision 3559b226e8ce77211e2c1bd7ddfb7686fec4d6dd
--gpu-memory-utilization {0.90 | 0.45}`, everything else default (resolved max_model_len 32,768). Client: harness,
`/v1/completions` streamed, prompt 128 / output 256 tokens (`usage.completion_tokens` = 256 on every request),
ignore_eos, temperature 0, start jitter 1 s, a 32-request warm-up wave per instance first (discarded). 4 vCPUs; the
VM's CPU was 13–15 % busy (all vCPUs) during every condition.

| condition | instance | users | output tok/s | harness steady tok/s | TTFT p50 / p95 ms | ITL p50 / p95 ms | TPOT p50 ms | running mean | KV pool (log) | KV usage mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline: 1 instance @ 0.90 | i1 | 32 | **1,081.4** | 1,076.6 | 403 / 528 | 26.2 / 30.0 | 29.1 | 31.5 | 287,072 | 0.029 |
| time-sharing, 2 @ 0.45, one busy | i1 | 16 | **813.0** | 813.7 | 136 / 240 | **17.9** / 23.6 | 19.6 | 15.9 | 109,168 | 0.038 |
| | i2 (idle) | 0 | 0.0 | — | — | — | — | 0.0 | 109,168 | 0.000 |
| time-sharing, 2 @ 0.45, both busy | i1 | 16 | 363.4 | 360.1 | 728 / 936 | **39.8** / 44.4 | 42.1 | 15.6 | 109,168 | 0.038 |
| | i2 | 16 | 366.1 | 360.5 | 732 / 935 | **39.9** / 44.1 | 42.1 | 15.6 | 109,168 | 0.037 |
| MPS, both busy | — | — | not run | | | | | | | |

| condition | **combined output tok/s** | joint window s | util.gpu mean % | SM clock mean (p50) MHz | power mean W | GPU memory used MiB | per process (nvidia-smi --query-compute-apps, mid-run) |
|---|---:|---:|---:|---:|---:|---:|---|
| baseline, 1 @ 0.90, 32 users | **1,081.4** | 21.2 | 100.0 | 1,246 (1,260) | 68.5 | 13,599 | EngineCore 13,148 MiB |
| time-sharing, one busy (16 users) | 813.0 | 13.2 | 100.0 | 1,222 (1,230) | 67.9 | 14,205 | EngineCore 6,892 + 6,862 MiB |
| time-sharing, both busy (16 + 16) | **729.5** | 31.6 | 100.0 | 1,235 (1,245) | 68.3 | 14,273 | EngineCore 6,926 + 6,896 MiB |
| MPS, both busy | not run | | | | | | |

Startup facts (logs): weights 1.95 GiB in every instance (same as the earlier single-instance log); available KV
memory 9.86 GiB at 0.90 and 3.75 GiB at 0.45; startup 187 s (baseline, cold), 108 s and 84 s for the two 0.45 instances.
No NVML throttle-counter time in any condition.

**What sharing one GPU cost.** Two instances with 16 users each made **729.5 output tok/s together, 33 % less than one
instance with 32 users (1,081.4)**, on the same GPU, same session, same total users. Each instance's ITL more than
doubled when the other one got busy (17.9 → 39.8 ms p50) and TTFT went from 136 to 728 ms p50. Per pair of steps, two
batches of 16 read the weights twice and run two sets of kernels one after the other, where one batch of 32 does it
once. One instance at 16 users alone already made 813 tok/s, more than both together.

**Over-allocation (instance 2 asks for 0.90 while instance 1 holds 0.45).** Start-up failure after 49 s, exit code 1,
exact error (`logs/server-overalloc-i2.log`):

```
ValueError: Free memory on device cuda:0 (7.82/14.56 GiB) on startup is less than desired GPU memory utilization (0.9, 13.11 GiB). Decrease GPU memory utilization or reduce GPU memory used by other processes.
RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}
```

vLLM's own start-up check is the only guard: instance 1 kept running, and instance 2 at 0.45 started fine afterwards.

**MPS: not run.** The budget guard skipped it: at 0.247 h of the 0.30 h part budget, the rule needed ≥ 0.07 h for MPS
(two server starts plus one load run). Row `mps-both-busy`, `budget: session 0.247 h`. So whether Kaggle allows
`nvidia-cuda-mps-control -d` is **not known** from this run. The stage code for MPS (start the daemon with
private pipe/log dirs, restart both instances under it, check `get_server_list` and the control log, quit) is ready.
Next step: `make t4-run STAGE=twoinst` with `--resume` of this run (it skips the finished conditions) in a session
with ≥ 0.15 h of budget.

**Cheap model for Part C** (same session, alone on the GPU, `--gpu-memory-utilization 0.30`): `Qwen/Qwen2.5-0.5B-Instruct`
@ `7ae557604adf67be50417f59c2c2f167def9a775`, weights **0.93 GiB**, available KV 2.63 GiB, 229,424 tokens, startup 124 s.

## Predicted vs measured

| Prediction | Predicted | Measured | Verdict / why |
|---|---|---|---|
| KV tokens per instance at 0.45 | ≈ 90,300 CALCULATED: (15 × 0.45 − 1.95 − 1.7) GiB ÷ 36,864 B | **109,168** (3.75 GiB) | +21 %. Two terms were off: vLLM sees **14.56 GiB** total, not 15.0 (error message above), so 0.45 is 6.55 GiB; and the non-KV, non-weight memory at 0.45 was **0.85 GiB** (6.55 − 1.95 − 3.75), not 1.7. At 0.90 it is 1.30 GiB (13.11 − 1.95 − 9.86): the working memory is not a constant |
| Combined (2 × 16) ≤ single (1 × 32) | combined ≤ single | **729.5 vs 1,081.4** (−33 %) | as predicted, by a wide margin |
| MPS somewhat better than time-sharing | better | not run (budget) | untested |
| ITL worse when both busy than one idle | worse | **39.8 vs 17.9 ms p50** (2.2×) | as predicted |
| Instance 2 at 0.90 fails to start | start-up failure | `ValueError: Free memory on device cuda:0 (7.82/14.56 GiB) … less than desired GPU memory utilization (0.9, 13.11 GiB)` | as predicted |

## Does NOT show

- No Kubernetes time-slicing configuration (NVIDIA device plugin `sharing.timeSlicing`): two processes on one GPU in one
  VM is the same CUDA time-sharing the plugin produces, but the plugin itself was not exercised.
- No MIG (T4 has none) and no MPS result (not run).
- AWQ INT4 only, one model, one workload (128/256, 16 + 16 or 32 users), one session, one repeat.
- NVML util.gpu, not DCGM; no per-process SM share.

## F3 — MPS for two instances (follow-up)

### Predictions (written before the F3 run, verbatim from the assignment)

MPS daemon may not be allowed in the Kaggle container; if it runs, combined output for 16 + 16 users rises above the time-sharing 729.5 tok/s but stays at or below the single-instance 1,081.4; ITL lower than 39.8 ms.

### Decisions made

- **F3 and F4 in one Kaggle session** (run 20261031-173838_followup). This saves one vLLM install. F3 ran first. The
  install (0.056 h with the `--help` dumps) is counted against F4. F3 is counted from its own start.
- **MPS daemon command:** `CUDA_MPS_PIPE_DIRECTORY=/tmp/goodput-mps/pipe CUDA_MPS_LOG_DIRECTORY=/tmp/goodput-mps/log
  CUDA_VISIBLE_DEVICES=0 nvidia-cuda-mps-control -d`. Both vLLM servers got the same two `CUDA_MPS_*` variables in
  their environment. Stop: `echo quit | nvidia-cuda-mps-control` with the same variables.
- **No time-sharing rerun in this session.** The budget covered only the MPS condition. The time-sharing (729.5) and
  single-instance (1,081.4) numbers below come from Build 14's session (20261031-085014_twoinst). That session ran at a
  different SM clock (next section).
- Everything else is as in Build 14:
  - Qwen2.5-3B-Instruct-AWQ @ `3559b226…`, `--dtype half --no-enable-prefix-caching --gpu-memory-utilization 0.45`.
  - The second instance started after the first was up.
  - 16 + 16 users, prompt 128 / output 256, ignore_eos, temperature 0, 3 requests per user.
  - One harness process per instance, after a 32-request warm-up wave per instance.
  - Output tok/s = `vllm:generation_tokens_total` deltas over the joint window (both instances ≥ 0.9 × users running).

### Run (20261031-173838_followup, Kaggle T4, real)

- Git `0fe5a61` (`-dirty` = only the results ledger `runs.jsonl` was uncommitted; the stage code is 0fe5a61), Tesla T4
  (GPU 0), driver 580.178.04, CUDA 13.0, vLLM 0.31.0, torch 2.13.0+cu130. F3 used **0.093 GPU-h** (marks `f3-begin` →
  `f3-end`).
- Command: `make t4-run STAGE=followup ARGS='--args "--parts f3,f4 --session-cap-h 0.48"'`.
- Rows `f3-*` in [followup.jsonl](20261031-173838_followup/results/followup/followup.jsonl). Raw logs are in
  `logs/mps-*.txt`, `logs/f3-nvidia-smi-both-up.txt` and `logs/server-f3-mps-i{1,2}.log`. Load data is in
  [f3-mps-both-busy/](20261031-173838_followup/results/followup/f3-mps-both-busy/).

**MPS is allowed on Kaggle.**
- `nvidia-cuda-mps-control -d` returned rc 0 with no output. The binaries are in `/opt/bin` (driver 580 / CUDA 13.0
  build), and the GPU compute mode is `Default`.
- The control log shows `Starting control daemon using socket /tmp/goodput-mps/pipe/control`, then `NEW SERVER 328:
  Ready`.
- Each vLLM EngineCore connected as a client. The log has `NEW CLIENT 306 …` and `NEW CLIENT 552 … Server already
  exists`, each just after a `User did not send valid credentials` line. Both clients were accepted.
- `nvidia-smi` with both servers up:

  ```
  |    0   N/A  N/A             306    M+C   VLLM::EngineCore                       6342MiB |
  |    0   N/A  N/A             328      C   nvidia-cuda-mps-server                   28MiB |
  |    0   N/A  N/A             552    M+C   VLLM::EngineCore                       6798MiB |
  ```

  Both EngineCores show type **M+C**, i.e. MPS clients. (The row's parsed `mps_client_lines` is empty because of a
  parsing bug in the stage: its regex expected a space before `MiB`. The raw file above is the evidence.)
- `echo quit | nvidia-cuda-mps-control` returned rc 0, and afterwards no `nvidia-cuda-mps` process was left.

| condition | session | **combined output tok/s** | per instance tok/s | ITL p50 / p95 ms (i1; i2) | TTFT p50 / p95 ms (i1; i2) | joint window s | util.gpu % | SM clock mean (p50) MHz | power mean W | KV pool i1 / i2 (log) |
|---|---|---:|---|---|---|---:|---:|---:|---:|---|
| **MPS, both busy (16 + 16)** | this run | **741.0** | 370.8 / 370.3 | **39.4** / 43.1; 39.4 / 43.0 | 565 / 925; 589 / 931 | 32.5 | 100.0 | **962 (975)** | 65.0 | 96,144 / 109,120 |
| time-sharing, both busy (16 + 16) | Build 14 | 729.5 | 363.4 / 366.1 | 39.8 / 44.4; 39.9 / 44.1 | 728 / 936; 732 / 935 | 31.6 | 100.0 | 1,235 (1,245) | 68.3 | 109,168 / 109,168 |
| one instance @ 0.90, 32 users | Build 14 | 1,081.4 | — | 26.2 / 30.0 | 403 / 528 | 21.2 | 100.0 | 1,246 (1,260) | 68.5 | 287,072 |

Notes on the MPS run:
- All 96 requests were OK, with `usage.completion_tokens` 256 each. Harness steady sum: 732.9 tok/s. There were 0
  preemptions and no NVML throttle-counter time.
- The VM CPU was 12.7 % busy. The client used 11 % of one core, and each server 17 %.
- GPU memory in use: 13,873 MiB. Instance 1 under MPS logged 3.30 GiB of available KV memory (96,144 tokens), against
  3.75 GiB without MPS in Build 14. Instance 2 logged 3.75 GiB (109,120). Startup took 174.9 s and 103.8 s.

**What this shows and what it does not.**
- Under MPS the two instances made **741.0 tok/s together**. That is +1.6 % over Build 14's time-sharing 729.5 and
  −31 % from the single instance 1,081.4.
- ITL p50 was 39.4 ms, against 39.8 under time-sharing.
- **The sessions are not comparable on clock.** This session's GPU ran at **962 MHz mean (80 °C, 65 W)**. Build 14's
  time-sharing run ran at **1,235 MHz**. CALCULATED: 741.0 × 1,235 / 962 = 951 tok/s if output scaled linearly with
  SM clock. That scaling is an assumption, not a measurement. So the +1.6 % is not a clean MPS effect. MPS may be worth
  more than that, or the clock gap may hide other differences.
- A same-session time-sharing vs MPS pair is the next step (below).

### Predicted vs measured (F3)

| Prediction | Measured | Verdict |
|---|---|---|
| MPS daemon may not be allowed in the Kaggle container | **allowed**: rc 0, MPS server started, both EngineCores `M+C` clients | the "may not" case did not happen |
| if it runs, combined 16 + 16 output rises above time-sharing 729.5 | **741.0** (+1.6 %) | above, but by less than the session-to-session clock difference (962 vs 1,235 MHz), so not shown to be an MPS effect |
| … but stays at or below the single instance 1,081.4 | 741.0 | as predicted |
| ITL lower than 39.8 ms | **39.4** ms p50 (p95 43.1 vs 44.4) | lower, by 1 %, within the same caveat |

### Does NOT show (F3)

- No same-session time-sharing or single-instance control. The comparison is with Build 14's session, at a ~22 %
  higher SM clock.
- One MPS run (96 requests, 32.5 s joint window), no repeat. No MPS settings were tuned
  (`CUDA_MPS_ACTIVE_THREAD_PERCENTAGE` was not set).
- MPS memory and fault isolation were not tested. Instance 1 got a smaller KV pool under MPS (96,144 vs 109,168
  tokens); why was not separated.
- **Next step:** one session that runs time-sharing both-busy, then MPS both-busy, back to back (`followup` stage F3
  plus Build 14's `start_pair("ts")` condition), ≈ 0.15 GPU-h.

## L3 — time-sharing vs MPS, back to back in one session (leftover)

### Predictions (written before the L3 run, verbatim from the assignment)

MPS > time-sharing by a measurable margin at the same clock; both < single instance.

### Decisions made

- **One session, three conditions in a fixed order:** (1) one instance at 0.90 with 32 users; (2) two instances at
  0.45, time-sharing, 16 + 16 users; (3) the MPS control daemon, then the same two instances, 16 + 16 users. The harness
  setup is Build 14's `load_condition`: in 128 / out 256, ignore_eos, temperature 0, 3 requests per user, start jitter
  1 s, one client process per instance. Each instance gets a discarded warm-up wave.
- **The order is not randomised.** One repeat of each condition fits the 0.3 h budget, not two. The SM clock is
  recorded per condition, so a clock difference between conditions is visible.
- **MPS-client check fixed.** `smi_process_lines` now accepts `6342MiB` (no space). It is unit-tested on the F3 raw file
  (`benchmarks/tests/test_notebook_helpers.py`). The `l3-mps-clients` row counts the EngineCores listed as `M+C`.
- Stage `leftover --parts l3,l4` (`leftover_l3`).

### Run (20261031-210126_leftover, Kaggle T4, real)

- Git `7991fde` (`-dirty`: uncommitted write-up files only), Tesla T4 GPU 0, driver 580.178.04, CUDA 13.0, vLLM 0.31.0
  (torch 2.13.0+cu130), `Qwen/Qwen2.5-3B-Instruct-AWQ` @ 3559b226 (full sha in the rows). L3 used **0.190 GPU-h**
  (marks `l3-begin` → `l3-end`). Serve flags: `--dtype half --no-enable-prefix-caching --revision … --gpu-memory-utilization
  {0.90 | 0.45}`. MPS: `CUDA_MPS_PIPE_DIRECTORY=/tmp/goodput-mps/pipe CUDA_MPS_LOG_DIRECTORY=/tmp/goodput-mps/log
  CUDA_VISIBLE_DEVICES=0 nvidia-cuda-mps-control -d` (rc 0, daemon running).
- **MPS clients verified:** row `l3-mps-clients` lists both EngineCores as MPS clients (`engine_cores_as_mps_clients: 2`):
  `917  M+C  VLLM::EngineCore  6798MiB` and `1070  M+C  VLLM::EngineCore  6798MiB`.
- Raw: rows `l3-single`, `l3-ts-both-busy`, `l3-mps-both-busy` and the `startup-l3-*` rows in
  [leftover.jsonl](20261031-210126_leftover/results/leftover/leftover.jsonl); per-condition directories with requests,
  `gpu.csv` (nvidia-smi columns), `cpu.csv`, `metrics.jsonl`; `logs/l3-nvidia-smi-mps-both-up.txt`.

| condition (order run) | combined output tok/s (server counters, joint window) | per instance | ITL p50 / p95 ms | TTFT p50 ms | SM clock MHz | power W | throttle reasons | util.gpu % | KV pool per instance |
|---|---:|---|---:|---:|---:|---:|---|---:|---:|
| 1. one instance @0.90, 32 users | **1,084.2** | 1,084.2 | 26.2 / 29.7 | 407 | 1,271 | 68.0 | sw_power_cap 100 % | 100 | 287,072 |
| 2. two @0.45, time-sharing, 16 + 16 | **720.4** | 360.9 / 359.5 | 40.2 / 45.0 (both) | 638 / 638 | 1,242 | 67.3 | sw_power_cap 100 % | 100 | 109,168 |
| 3. same two under MPS, 16 + 16 | **798.0** | 399.2 / 398.8 | 36.3 / 40.4 (both) | 545 / 469 | **1,061** | 66.1 | sw_power_cap 100 % | 100 | 109,120 |

Harness steady output tok/s (sum): 1,079.4 / 711.8 / 788.7. Joint full-batch windows: 21.2 / 33.6 / 28.5 s. Every request
succeeded (96 / 96 + 96 / 96 + 96).

- **MPS beats time-sharing by +10.8 %** (798.0 vs 720.4 tok/s), with ITL p50 −9.5 % (36.3 vs 40.2 ms), in the same session,
  4 minutes apart.
- **The clocks were not equal:** the MPS condition ran at 1,061 MHz, time-sharing at 1,242 (−14.6 %), both with
  sw_power_cap active in every sample at 66–67 W. Per MHz (CALCULATED) MPS made 0.752 tok/s per MHz vs 0.580: +30 %. With
  MPS both processes' kernels run at the same time, the card draws its cap at a lower clock and still finishes more work.
- **Both shared setups lose to one instance:** −33.6 % (time-sharing) and −26.4 % (MPS) vs 1,084.2.

### Predicted vs measured (L3)

| Prediction | Measured | Verdict |
|---|---|---|
| MPS > time-sharing by a measurable margin at the same clock | +10.8 % combined tok/s, ITL p50 −9.5 %; but **not at the same clock**: 1,061 vs 1,242 MHz (+30 % per MHz) | **direction as predicted**; the "same clock" condition did not hold — MPS ran at a lower clock and still won |
| both < single instance | 720.4 and 798.0 vs 1,084.2 | **as predicted** |

### Does NOT show (L3)

- One run per condition, fixed order (single → time-sharing → MPS); the card warmed from 68 to 80 °C over the three.
  Whether the lower MPS clock is caused by MPS or by order / temperature is not separated.
- MPS memory and fault isolation, `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE` and uneven loads were not tested.

## Build 17 — single vs time-sharing vs MPS, one session, alternating order, per MHz

Kaggle T4, real. Same model, serving flags and harness setup as L3 (read from run 20261031-210126_leftover, rows
`startup-l3-*` / `l3-*`): Qwen/Qwen2.5-3B-Instruct-AWQ @ 3559b226e8ce77211e2c1bd7ddfb7686fec4d6dd, vLLM 0.31.0,
`--dtype half --no-enable-prefix-caching --revision <sha> --gpu-memory-utilization {0.90 | 0.45}`; prompt 128 / output 256
tokens, ignore_eos, temperature 0, max_tokens jitter 0, start jitter 1 s, streamed `/v1/completions`, one client process per
instance, a discarded 32-request warm-up wave per instance.

Conditions:
- **S** = one instance @ 0.90, 32 users.
- **T** = two instances @ 0.45, plain time-sharing (no MPS daemon), 16 + 16 users, both busy.
- **M** = the same two instances under MPS (daemon with `CUDA_MPS_PIPE_DIRECTORY` / `CUDA_MPS_LOG_DIRECTORY`), 16 + 16 users.

Order S T M M T S in one session; same measured window for every condition.

### Predictions (written before the Build 17 run, verbatim from the assignment)

- Combined output tok/s: S > M > T.
- Per MHz (output tok/s ÷ mean SM clock): M > T by a measurable margin (> 5 %); the raw-tok/s gap may be smaller or larger than per-MHz because MPS may change the clock.
- sw_power_cap active most of the time in all three; clock differs between conditions by more than run-to-run noise within a condition.
- ITL p50: M ≤ T.

### Decisions made

- **Stage `mpsab`** (new, `benchmarks/kaggle/t4_notebook.py`), kernel slug `goodput-t4-b17k` (a separate slug, so no other
  checkout's kernel is overwritten; the model is ungated, no HF token needed).
- **Fixed measured window instead of L3's request count.** L3's closed loop ran 3 requests per user and measured the
  "joint full-batch window" (21–34 s, different per condition). Here each client runs closed-loop for `ramp 5 s + window
  90 s` and every in-flight request is cancelled at the window end. Output tok/s = output-token chunks that arrived inside
  the 90 s window ÷ 90 s (client-side, per instance, summed for the combined number); the server's
  `generation_tokens_total` rate over the same window is recorded next to it. ITL = gaps with both chunks inside the window;
  TTFT = requests sent inside the window. The request body is the harness's `client.request_body` (L3's), prompt 128 /
  output 256, ignore_eos, temperature 0, max_tokens jitter 0, start jitter 1 s.
- **Prompts made once** (512, 128 tokens each, harness `make_prompts`, seed 17) on the first server and reused in every
  condition (S: all 512; T/M: even ones to instance 1, odd ones to instance 2). Prefix caching is off, so reuse is not a
  cache effect; it keeps the prompt set identical across conditions.
- **Warm-up as L3:** one discarded 32-request wave (16 output tokens) per instance before the load.
- **Instance 2 start:** launched as soon as instance 1 logs `Available KV cache memory` (instance 1 has profiled; its KV
  allocation and second graph capture follow within ~13 s). Instance 2's own memory check comes ~40 s after its launch
  (L3 log: launch → EngineCore init 41 s). This saves ~20 s per pair; the KV pool of every instance is recorded so any
  effect on memory sizing is visible.
- **MPS per M condition:** a fresh daemon (same command as L3: `CUDA_MPS_PIPE_DIRECTORY=/tmp/goodput-mps/pipe
  CUDA_MPS_LOG_DIRECTORY=/tmp/goodput-mps/log CUDA_VISIBLE_DEVICES=0 nvidia-cuda-mps-control -d`) before the engines,
  `echo quit | nvidia-cuda-mps-control` after. In S and T the `CUDA_MPS_*` variables are removed from the environment.
  With the engines up, `nvidia-smi` and `pgrep -fa nvidia-cuda-mps` are saved: M needs both EngineCores `M+C`; S/T need no
  `M+C` row and no MPS process (`mps_state_ok` per row).
- **Idle:** ≥ 30 s with no engine before each condition (counted from the last engine's exit); temperature, SM clock and
  power are read at the end of the idle and again at load start. Condition 1 follows the install (no engine before it).
- **Model prefetch** (`huggingface_hub.snapshot_download`, pinned revision) runs next to the vLLM install, to take the
  download out of the first engine start.
- **Budget guard 0.5 h** (script session time, install included): a condition starts only if its estimate (engine start
  85 s single / 150 s pair / 175 s cold, + idle left + 25 + 5 + 90 + 10 s) fits; otherwise it and all later ones are
  skipped and recorded. Estimate for all six: ~0.53 h, so the last S may be cut.
- **Per MHz** = output tok/s ÷ mean SM clock (`clocks.sm` from nvidia-smi, 1 Hz, same 90 s window); CALCULATED offline.

### Run (20261103-070741_mpsab, Kaggle T4, real)

- Command: `.venv/bin/python -m benchmarks.kaggle.run_kaggle --stage mpsab --kernel goodput-t4-b17k` (stage defaults:
  order `S,T,M,M,T,S`, ramp 5 s, window 90 s, idle 30 s, budget 0.5 h). Git `a6d0112` (clean at push).
- Session: script **1,734.8 s = 0.482 GPU-h** (push→done 29.9 min = 0.498 h upper bound). uv install 260.9 s; model
  prefetch next to it 17.8 s (rc 0). `vllm serve --help=all` listed every flag used (`missing: []`).
- Tesla T4, **GPU index 0, UUID `GPU-f8017916-967f-a4ba-73f0-217d761c65e3`**, bus 00000000:00:04.0, driver 580.178.04,
  CUDA 13.0 (driver), power limit / enforced / default **70.00 W**. VM: 2 × T4 (only GPU 0 used), 4 vCPUs. vLLM 0.31.0,
  torch 2.13.0+cu130. Model `Qwen/Qwen2.5-3B-Instruct-AWQ` @ `3559b226e8ce77211e2c1bd7ddfb7686fec4d6dd`.
- Serve flags: `--dtype half --no-enable-prefix-caching --revision 3559b226e8ce77211e2c1bd7ddfb7686fec4d6dd
  --gpu-memory-utilization {0.9 | 0.45}` (plus `--port 8000/8001 --served-model-name <model>`), everything else default.
- Client per instance: `/v1/completions` streamed, prompt 128 / max_tokens 256, ignore_eos, temperature 0, max_tokens jitter
  0, start jitter 1 s, closed loop with 32 (S) or 16 + 16 (T, M) users, ramp 5 s, **measured window 90.0 s in every run**,
  then in-flight requests cancelled. Every completed request returned `usage.completion_tokens` = 256; **0 errors and 0
  preemptions** in every run.
- **The 6th condition (second S) did not run:** row `cond-6S`, `budget: session 0.482 h + estimate 242 s > 0.5 h`. So S has
  one run; T and M have two each.
- MPS state, from the saved `nvidia-smi` and `pgrep -fa nvidia-cuda-mps` with the engines up (`logs/nvidia-smi-<run>-up.txt`,
  `logs/pgrep-mps-<run>.txt`):
  - 3M: `908 M+C VLLM::EngineCore 6798MiB`, `1059 M+C VLLM::EngineCore 6798MiB`; processes `850 nvidia-cuda-mps-control -d`,
    `927 nvidia-cuda-mps-server`.
  - 4M: `1278 M+C …EngineCore 6798MiB`, `1429 M+C …EngineCore 6798MiB`; `1220 nvidia-cuda-mps-control -d`, `1297 nvidia-cuda-mps-server`.
  - 1S, 2T, 5T: no `M+C` row (5T: `1626 C VLLM::EngineCore`, `1770 C VLLM::EngineCore`), `pgrep` rc 1 (no MPS process).
  - Daemon start rc 0 both times (compute mode `Default`); `echo quit | nvidia-cuda-mps-control` rc 0, nothing left.
- KV pools as in L3: 287,072 tokens (S), 109,168 per instance (T), 109,120 per instance (M). Instance 2 was launched 64–69 s
  after instance 1 (at instance 1's `Available KV cache memory` line); startups 171.0 s (S, cold), 114.8 / 84.2 s (2T),
  79.8 / 79.7 (3M), 83.9 / 83.9 (4M), 83.8 / 83.9 (5T).
- Raw: rows `cond-*`, `cond-*-state`, `startup-*` in [mpsab.jsonl](20261103-070741_mpsab/results/mpsab/mpsab.jsonl);
  per run `cond-<n><X>/` with `gpu.csv` (1 Hz NVML + nvidia-smi clocks / power / limits / throttle reasons), `cpu.csv`,
  `requests-i*.jsonl.gz` (every request with its token-chunk times), `compute-apps.txt`; tables by
  `python -m benchmarks.kaggle.report_mpsab benchmarks/results/t4/20261103-070741_mpsab`
  ([report.md](20261103-070741_mpsab/results/mpsab/report.md), [analysis.json](20261103-070741_mpsab/results/mpsab/analysis.json)).

#### Per run (Kaggle T4, real; per MHz CALCULATED)

All numbers over the 90 s window. Output tok/s = client-side token chunks in the window ÷ 90 s; "server ctr" = the
`generation_tokens_total` rate over the same window. TTFT / ITL pooled over both instances. SM clock = nvidia-smi
`clocks.sm`, 90 samples per run. Temperature: at the end of the idle before the condition / mean in the window.

| # | cond | rep | timestamp (UTC, row) | combined tok/s | per instance | server ctr | tok/s per MHz | TTFT p50 / p95 ms | ITL p50 / p95 ms | SM clock mean (min–max) MHz | power W (limit) | temp °C start / window | throttle reasons (% of samples) | KV usage peak |
|---|---|---|---|---:|---|---:|---:|---|---|---|---|---|---|---|
| 1 | S | 1 | 12:17:13 | **1,008.7** | 1,008.7 | 1,006.8 | 0.8312 | 430 / 649 | 27.0 / 31.3 | 1,214 (1,005–1,335) | 68.3 (70.0) | 39 / 72.4 | sw_power_cap 100, others 0 | 0.043 |
| 2 | T | 1 | 12:22:01 | **694.8** | 347.3 / 347.5 | 694.9 | 0.5699 | 577 / 1,008 | 40.5 / 45.6 | 1,219 (1,050–1,290) | 67.4 (70.0) | 64 / 77.4 | sw_power_cap 100, others 0 | 0.056 / 0.056 |
| 3 | M | 1 | 12:26:44 | **783.1** | 392.2 / 390.9 | 788.5 | 0.7170 | 451 / 689 | 35.7 / 41.7 | 1,092 (945–1,200) | 67.5 (70.0) | 64 / 77.4 | sw_power_cap 100, others 0 | 0.056 / 0.056 |
| 4 | M | 2 | 12:31:39 | **782.8** | 391.8 / 391.0 | 789.3 | 0.7184 | 472 / 709 | 35.7 / 41.5 | 1,090 (975–1,230) | 67.7 (70.0) | 63 / 77.4 | sw_power_cap 100, others 0 | 0.056 / 0.056 |
| 5 | T | 2 | 12:36:33 | **695.5** | 347.7 / 347.8 | 696.0 | 0.5672 | 738 / 994 | 40.6 / 45.7 | 1,226 (1,065–1,290) | 67.8 (70.0) | 63 / 77.5 | sw_power_cap 100, others 0 | 0.056 / 0.056 |
| 6 | S | 2 | — | not run (budget guard) | | | | | | | | | | |

"Others" = hw_slowdown, hw_thermal_slowdown, sw_thermal_slowdown, hw_power_brake_slowdown, gpu_idle,
applications_clocks_setting (all 0 % of samples). NVML's throttle-reason **counters** (`nvidia-smi -q -d PERFORMANCE`)
moved by 0 µs in every run, as in earlier builds; the per-sample reason flag is the evidence used here. util.gpu 100 % in
every run; VM CPU 15–19 % busy.

#### Per condition (mean of the runs; spread = (max − min) ÷ mean; CALCULATED)

| cond | runs | combined tok/s (spread) | tok/s per MHz (spread) | ITL p50 ms (spread) | ITL p95 ms | TTFT p50 ms | SM clock mean MHz (spread) | power W | throttle reasons | output tok/J |
|---|---|---|---|---|---:|---:|---|---:|---|---:|
| **S** | 1 (1S) | **1,008.7** (n/a) | **0.8312** (n/a) | 27.05 (n/a) | 31.26 | 430 | 1,214 (n/a) | 68.3 | sw_power_cap 100 % | 14.77 |
| **T** | 2 (2T, 5T) | **695.2** (0.09 %) | **0.5685** (0.47 %) | 40.52 (0.27 %) | 45.68 | 657 | 1,223 (0.56 %) | 67.6 | sw_power_cap 100 % | 10.28 |
| **M** | 2 (3M, 4M) | **783.0** (0.04 %) | **0.7177** (0.20 %) | 35.71 (0.17 %) | 41.58 | 462 | 1,091 (0.23 %) | 67.6 | sw_power_cap 100 % | 11.58 |

Output tok/J = combined tok/s ÷ mean power (CALCULATED).

- **M vs T: +12.6 % raw tok/s, +26.2 % per MHz** (0.7177 vs 0.5685), at a **10.8 % lower SM clock** (1,091 vs 1,223 MHz)
  and the same power (67.6 W, at the 70 W cap in every sample). ITL p50 −11.9 % (35.7 vs 40.5 ms), p95 −9.0 %.
- **Verdict: yes — the M vs T per-MHz difference (+26.2 %) is ~56 times the larger within-condition spread (T 0.47 %, M
  0.20 %), so in this session MPS does more work per MHz than plain time-sharing, well beyond repeat-to-repeat noise.**
- vs S (one run): T −31.1 % and M −22.4 % in raw tok/s; per MHz T −31.6 %, M −13.7 %. S ran at about T's clock (1,214 vs
  1,223 MHz, −0.8 %, within T's own 0.56 % spread plus S's lack of a repeat).
- **Order:** repeat 2 vs repeat 1 moved T by +0.09 % (tok/s) / −0.47 % (per MHz) and M by −0.04 % / +0.20 %; clock
  1,219 → 1,226 (T) and 1,092 → 1,090 (M); start temperatures 64 → 63 °C both. Order does not move the numbers beyond
  ~0.5 %. **S is not order-controlled:** its only run came first, started from 39 °C (after the install) and ran at 72.4 °C
  mean vs 77.4 °C for every other run.
- TTFT p50 varied within T (577 vs 738 ms) more than any other metric; closed-loop requests with identical lengths
  arrive in waves, so TTFT depends on where the window cuts the waves. tok/s and ITL did not.
- Against L3 (one run each, request-count windows of 21–34 s): L3 had 1,084.2 / 720.4 / 798.0 tok/s at 1,271 / 1,242 /
  1,061 MHz. Same direction and similar M/T clock gap; the absolute numbers differ (different window definition, different
  session and clock).

#### Predicted vs measured (Build 17)

| Prediction (verbatim) | Measured | Verdict |
|---|---|---|
| Combined output tok/s: S > M > T. | 1,008.7 > 783.0 > 695.2 | **as predicted** (S from one run) |
| Per MHz: M > T by a measurable margin (> 5 %); the raw-tok/s gap may be smaller or larger than per-MHz because MPS may change the clock. | per MHz **+26.2 %** (spreads 0.2–0.5 %); raw +12.6 %, smaller, because M ran at a 10.8 % lower clock | **as predicted**; the raw gap is the smaller one |
| sw_power_cap active most of the time in all three; | 100 % of the samples in every run of S, T and M; no other reason active | **as predicted** (all of the time) |
| clock differs between conditions by more than run-to-run noise within a condition. | M vs T −10.8 % vs within spreads 0.23 % / 0.56 %: **yes**. S vs T −0.8 %, inside T's 0.56 % spread plus an unrepeated S: **no** | **partly**: true for M vs S/T, not for S vs T |
| ITL p50: M ≤ T. | 35.7 vs 40.5 ms | **as predicted** |

#### Does NOT show (Build 17)

- One T4 type (Kaggle, 70 W cap), one session, one GPU (index 0) of that VM.
- AWQ INT4 only (Qwen2.5-3B-Instruct-AWQ), one workload (128 in / 256 out, equal lengths), two instances only, equal
  16 + 16 load; no uneven loads, no `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE`, no MPS memory / fault isolation.
- S has a single run (the 0.5 h guard cut the second), so S's spread and order effect are unmeasured, and S ran cooler.
- No Kubernetes time-slicing configuration (NVIDIA device plugin `sharing.timeSlicing`) and no device-plugin MPS mode: the
  processes ran directly in one VM. No MIG (T4 has none).
- Per MHz is a normalisation (tok/s ÷ mean clock), not a measured clock-scaling law; the clock was not pinned (the power
  cap set it). Why MPS runs at a lower clock at the same power (more concurrent SM activity per watt is the likely reason)
  is not measured: no DCGM / per-SM counters.

### Build 17 rerun — full order S T M M T S (decision written before the rerun)

- Why: the first session (20261103-070741_mpsab) skipped the 6th condition (second S) at the 0.5 GPU-h guard, so S had one
  run and no repeat spread. With more Kaggle quota available, the whole order is rerun in **one new session** rather than
  S alone, so all three conditions are again measured within one session (an S-only session would not be matched to the
  first session's M and T).
- Same code (stage `mpsab`, unchanged since a6d0112), same defaults (order S,T,M,M,T,S; ramp 5 s; window 90 s; idle 30 s;
  same prompts seed 17); only `--budget-h` is raised from 0.5 to 0.8 so the guard does not cut the 6th condition.
- Predictions are those above, unchanged. The first session's numbers stay as they are; the rerun is reported next to them,
  and the cross-session difference is reported as a session-to-session check, not merged into one mean.

### Rerun (20261103-090230_mpsab, Kaggle T4, real) — all six conditions

- Kernel `raviveldanda/goodput-t4-b17k` version 2, git `c094332` (stage code identical to `a6d0112`), args `--budget-h 0.8`,
  status complete. Script session 1,796.7 s = **0.499 GPU-h** (push→done 30.9 min = 0.515 h upper bound).
- **Different physical GPU** from the first session: GPU 0 UUID `GPU-6fd67248-f4aa-08f4-852c-2fe8ff3591d7` (first session
  `GPU-f8017916-967f-a4ba-73f0-217d761c65e3`); same driver 580.178.04, CUDA 13.0, 70 W limit, vLLM 0.31.0.
- Every run: 90.0 s window, 0 errors, 0 preemptions, every completed request 256 completion tokens, sw_power_cap active in
  100 % of 1 Hz samples and no other throttle reason. MPS check: 3M and 4M have both EngineCores as `M+C` clients; 1S, 2T, 5T,
  6S have none. KV pools: S 287,072 (1S) and **300,048 (6S**, "Available KV cache memory" 10.3 GiB vs 9.86 GiB in 1S — logged
  as is, not explained here; KV peak use was ≤ 5.6 % in every run so the pool never bound), T 109,168, M 109,120 — the same as the first session.
- Report: `results/mpsab/report.md` (`python -m benchmarks.kaggle.report_mpsab benchmarks/results/t4/20261103-090230_mpsab`).

#### Per run (Kaggle T4, real; per MHz CALCULATED)

| # | cond | tok/s | per instance | tok/s per MHz | TTFT p50/p95 ms | ITL p50/p95 ms | SM clock mean (min–max) MHz | power W | temp °C start / window |
|---|---|---:|---|---:|---|---|---|---:|---|
| 1 | S | 950.0 | — | 0.8374 | 472 / 632 | 28.4 / 33.5 | 1,134 (900–1,290) | 67.0 | 39 / 71.3 |
| 2 | T | 643.2 | 321.6 / 321.6 | 0.5841 | 833 / 1,046 | 43.7 / 49.2 | 1,101 (990–1,170) | 65.9 | 64 / 77.4 |
| 3 | M | 730.1 | 365.1 / 365.0 | 0.7541 | 616 / 1,018 | 38.5 / 42.4 | 968 (840–1,050) | 65.9 | 64 / 77.5 |
| 4 | M | 729.5 | 364.8 / 364.7 | 0.7549 | 607 / 893 | 38.2 / 42.1 | 966 (810–1,065) | 66.0 | 63 / 77.3 |
| 5 | T | 645.3 | 320.2 / 325.2 | 0.5855 | 779 / 1,023 | 43.7 / 50.7 | 1,102 (1,020–1,170) | 66.2 | 63 / 77.4 |
| 6 | S | 919.0 | — | 0.8603 | 510 / 777 | 29.6 / 34.2 | 1,068 (915–1,185) | 66.0 | 64 / 76.9 |

#### Per condition (mean of 2 runs; spread = (max − min) ÷ mean; CALCULATED)

| cond | tok/s (spread) | per MHz (spread) | ITL p50 ms (spread) | ITL p95 ms | TTFT p50 ms | SM clock MHz (spread) | power W | output tok/J |
|---|---|---|---|---:|---:|---|---:|---:|
| S | 934.5 (3.32 %) | 0.8488 (2.70 %) | 29.01 (4.31 %) | 33.9 | 491 | 1,101 (6.02 %) | 66.5 | 14.06 |
| T | 644.3 (0.33 %) | 0.5848 (0.24 %) | 43.68 (0.00 %) | 49.9 | 806 | 1,102 (0.09 %) | 66.0 | 9.76 |
| M | 729.8 (0.09 %) | 0.7545 (0.11 %) | 38.35 (0.72 %) | 42.3 | 612 | 967 (0.19 %) | 66.0 | 11.07 |

- M vs T: raw tok/s **+13.3 %**, per MHz **+29.0 %** (121× the larger within-condition spread, 0.24 %), clock −12.2 %, ITL p50 −12.2 %.
- S vs T: raw +45.0 %, per MHz +45.1 %, clock −0.0 %. S vs M per MHz +12.5 %.
- Order: T +0.33 % and M −0.09 % tok/s between repeats. **S is the only condition with an order effect**: 6S (started at
  64 °C) vs 1S (started at 39 °C) −3.3 % tok/s at −5.8 % clock, while per MHz went **up** 2.7 %.

#### Both sessions side by side (CALCULATED from the two per-condition tables)

| | session 1 (070741, GPU-f801…) | session 2 (090230, GPU-6fd6…) | s2 vs s1 |
|---|---|---|---|
| S tok/s (runs) | 1,008.7 (1) | 934.5 (2) | −7.4 % |
| T tok/s | 695.2 | 644.3 | −7.3 % |
| M tok/s | 783.0 | 729.8 | −6.8 % |
| T / M SM clock MHz | 1,223 / 1,091 | 1,102 / 967 | −9.9 % / −11.3 % |
| T / M per MHz | 0.5685 / 0.7177 | 0.5848 / 0.7545 | +2.9 % / +5.1 % |
| M vs T raw tok/s | +12.6 % | +13.3 % | |
| M vs T per MHz | +26.2 % | +29.0 % | |
| M vs T ITL p50 | −11.9 % | −12.2 % | |
| M vs T clock | −10.8 % | −12.2 % | |

#### Verdict (both sessions)

**MPS beats time-sharing on this T4 in both sessions, on two different physical GPUs: +12.6 % / +13.3 % raw output tok/s and
+26.2 % / +29.0 % per MHz, with ITL p50 about 12 % lower, while running 11–12 % lower SM clock at the same power.**

Caveat on per MHz, from this rerun's own data: per MHz is not clock-invariant. The two S runs differ by 5.8 % in clock and
per MHz rose 2.7 % at the lower clock; across sessions, a ~10 % lower clock gave +2–5 % per MHz. So part of M's per-MHz
lead (M always runs at the lower clock) is the normalisation, not MPS. The raw tok/s gap (+12.6 % / +13.3 %, measured at the
**lower** clock for M) does not depend on the normalisation and is the conservative number to quote.

#### Predicted vs measured (rerun)

| Prediction | Measured (session 2) | Verdict |
|---|---|---|
| S > M > T | 934.5 > 729.8 > 644.3 tok/s, both S runs > every M run | as predicted |
| M > T per MHz by > 5 % | +29.0 % (raw +13.3 %) | as predicted |
| sw_power_cap most of the time | 100 % of samples, every run | as predicted |
| clock differs between conditions beyond noise | M vs T −12.2 % yes; S vs T −0.0 % no (S's own spread 6.0 %) | partly (same as session 1) |
| ITL p50 M ≤ T | 38.35 vs 43.68 ms | as predicted |

#### Does NOT show (rerun)

- Why 6S got a larger KV pool than 1S (10.3 vs 9.86 GiB available); it did not limit anything here.
- A clock-invariant efficiency measure: per MHz moves with the clock (see caveat); clocks were not locked in this build
  (locking with `nvidia-smi -lgc` was not attempted, so whether Kaggle allows it is untested).
- Why the second session's GPU ran ~10 % lower clocks at the same 70 W cap (different physical card; one session each).
