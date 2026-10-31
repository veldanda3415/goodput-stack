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
