# HTTP vs offline at 384 users, and a replay of the old 64-user sweep point (Kaggle T4, real)

Follow-up F1 to the ridge work ([ridge.md](ridge.md)). Questions: (a) what does serving through `vllm serve` + a
Python HTTP client cost against the offline engine ceiling at 384 sequences, and (b) was the old 615 output tok/s at
64 users (run 20261014-220946_sweep) limited by the GPU or by the client?

## Predictions (written before the F1 run, verbatim from the assignment)

- F1a HTTP at 384 users, same settings as offline: output 1,100–1,400 tok/s, below the offline 1,459; client CPU the likely limiter on 4 vCPUs.
- F1b replay of the old sweep point (64 users, prompt 256 / output 128 ± 25 %, max-num-batched-tokens 2,048): output within ±10 % of 615 tok/s, util.gpu ≈ 100 %, client CPU well below saturation → the old number was GPU-limited.
- F1c same as F1b with max-num-batched-tokens 8,192: small change (< 10 %).

## Decisions made

- **F1 and F2 in one Kaggle session.** Each push re-installs vLLM (199 s this time). One session for both saves one
  install. The install counts against F1. F2 has its own 0.15 h budget, measured from its own start.
- **Client: the repo harness, not `vllm bench serve`.** It is the same client as the old sweep, so F1b is a
  like-for-like replay, and it measures CPU per client process. F1a used **4 spawned client processes × 96 streams**
  (384 streams), 2 requests per stream (768 requests). A second F1a run with 1 process × 384 streams was planned only if
  ≥ 0.15 h of the F1 budget was left. There was 0.085 h left, so it was skipped (row `f1a-u384-p1`).
- **F1a settings = the Build 14 offline settings:** `--gpu-memory-utilization 0.95 --max-num-seqs 384
  --max-num-batched-tokens 8192`, prefix caching off, max-model-len default (32,768). Prompt 128 / output 256 fixed,
  ignore_eos, temperature 0, start jitter 1 s per stream.
- **F1b = the old server flags plus an explicit `--max-num-batched-tokens 2048`.** The old flags were `--dtype half
  --gpu-memory-utilization 0.9 --max-model-len 4096 --no-enable-prefix-caching`. 2,048 is what vLLM resolves for
  those flags anyway (ridge.md Task 0). `--revision aa8e7253…` was added; the old run used the same revision. The
  client config is the same `client` dict as row `closed-mnsdefault-c64` (prompt 256, max_tokens 128 ± 25 %, start
  jitter 1 s, ignore_eos, temperature 0, 256 requests, 2 sequential warm-up requests).
- **Warm-up.** Each server got one discarded wave first: 32 concurrent requests, 16 output tokens. In the old sweep the
  c=64 point ran after the c=1…32 points on a server that was already warm.
- **Windows.** "Run window" = first measured request sent → last measured request finished (from the request records).
  This is the window Task 0 used. "Full window" = /metrics samples with running ≥ 0.9 × users. Output tok/s: the
  harness steady window (the old sweep's number) and `vllm:generation_tokens_total` deltas. CPU: psutil at 1 Hz,
  % of one core per process tree. "Server" = the `vllm serve` process plus its children. "API" = that process alone.
  "EngineCore" = its children.
- **Budget guard.** A later F1 server start needed ≥ 0.045 h of the F1 budget left.

## Run (20261031-171557_followup, Kaggle T4, real)

- Session: script session 1,288 s = **0.358 GPU-h** for F1 + F2. F1 = 0.224 h, including the 199 s uv install and the
  `--help` dumps (`f1-begin` / `f1-end` marks).
- Software and hardware: git `0593862`, Tesla T4 (GPU 0 only), driver 580.178.04, CUDA 13.0 (driver), vLLM 0.31.0
  (torch 2.13.0+cu130). Model `Qwen/Qwen2.5-3B-Instruct` @ `aa8e72537993ba99e69dfaafa59ed015b17504d1`, FP16
  (`--dtype half`). 4 vCPUs.
- Flag names: checked against `vllm serve --help=all` and `vllm bench throughput --help=all`
  (`logs/vllm-serve-help-0.31.0.txt`, `logs/vllm-bench-throughput-help.txt`). The server logs' `non-default args` and
  `max_num_batched_tokens` lines confirm the settings.
- Command: `make t4-run STAGE=followup ARGS='--args "--parts f1,f2"'`.
- Raw data: [followup.jsonl](20261031-171557_followup/results/followup/followup.jsonl), and per run:
  [f1a-u384-p4/](20261031-171557_followup/results/followup/f1a-u384-p4/) and
  [f1b-u64-mbt2048/](20261031-171557_followup/results/followup/f1b-u64-mbt2048/). Each run directory holds
  requests.jsonl, metrics.jsonl, gpu.csv and cpu.csv.

| run | server flags (besides `--dtype half --no-enable-prefix-caching --revision`) | users × procs | KV pool (log) | **output tok/s** harness steady | output tok/s server, run window (full window) | total tok/s server, run window | TTFT p50 / p95 ms | ITL p50 / p95 ms | running mean (full) | waiting mean | KV usage mean / max (run window) | util.gpu mean % | SM clock mean (p50) MHz | power mean W | client CPU % of one core, per process | server CPU %: tree / API / EngineCore | VM CPU % of 4 vCPUs, load1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| **F1a** | util 0.95, max-num-seqs 384, max-num-batched-tokens 8,192 | 384 × 4 | 192,112 | **1,471.2** (4 × ~367.8) | **1,464.5** (1,615.9) | 2,199.0 | 7,708 / 13,886 | 204.0 / 249.5 | 353.6 (371.4) | 9.1 | 0.472 / 0.768 | 99.97 | 981 (1,020) | 67.5 | 7.2 / 7.0 / 7.1 / 6.9 (sum 28.3, max 96.2) | 23.1 / 16.1 / 7.0 | 14.1, 1.02 |
| **F1b** | util 0.9, max-model-len 4,096, max-num-batched-tokens 2,048, max-num-seqs default | 64 × 1 | 175,008 | **610.1** | 612.5 (660.3) | 1,823.0 | 473 / 3,681 | 64.9 / 208.9 | 56.9 (62.6) | 1.06 | **0.106 / 0.129** | 100.0 | 971 (960) | 67.1 | 9.0 (max 13.9) | 24.0 / 8.8 / 15.2 | 9.3, 0.57 |
| F1c | F1b + max-num-batched-tokens 8,192 | — | — | **not run** | | | | | | | | | | | | | |

All 768 / 256 requests OK, 0 errors. `usage.prompt_tokens` was 128 / 256. `usage.completion_tokens` was 256 on every
F1a request and 96–160 in F1b. Preemptions were 0 in both. Means are over the run window unless marked "full".

**F1c: not run.** After F1b the F1 budget had 0.026 h left. A server start plus the run needs ≈ 0.05 h, so the guard
skipped it (row `f1c-u64-mbt8192`, reason `F1 budget: 0.026 h left`). The F1a 1-process run was also skipped (above).

### (a) HTTP + client vs offline at 384 sequences

- **The HTTP path cost nothing measurable.** Through `vllm serve` and 4 harness processes, output was **1,464.5 tok/s**
  by server counters over the run window and **1,471.2** by the harness. The Build 14 offline ceiling at max-num-seqs
  384 was 1,458.6. Total tok/s was 2,199.0 vs 2,187.9 offline. Over the full-batch window (all 384 running,
  ramp-up excluded) the server made 1,615.9 output tok/s.
- **The client was not a limit.**
  - Each of the 4 client processes used ~7 % of one core (max 25 %), 28 % of one core together.
  - The `vllm serve` tree used 23 % of one core: API server 16 %, EngineCore 7 %.
  - The 4-vCPU VM was 14 % busy, with load average ~1.
  - The GPU sat at util.gpu 100 %, 67.5 W of 70 W and ~1.0 GHz SM clock. That is the same power-capped state as
    offline (967 MHz mean at 384 in Build 14).
- ITL p50 204 ms and p95 250 ms match the ~250 ms per engine step CALCULATED from the offline 384 point.
- TTFT p50 was 7.7 s because 384 prompts arrive within 1 s and queue behind each other's prefill.
- **Caveat:** the offline number comes from the Build 14 session (20261031-082141), not this one. Clocks were similar
  (offline 967 MHz mean, here 981), but this is a cross-session comparison. Offline also samples at temperature 1.0
  (hard-coded in the tool); HTTP used 0.

### (b) Was the old 615 tok/s GPU-limited or client-limited?

**GPU-limited.**
- The replay made **610.1 tok/s** (harness steady, the old metric), −0.9 % from 615.46.
- ITL p50 / p95 were **64.9 / 208.9 ms**, against the old 64.6 / 208.4 ms.
- util.gpu was 100 % in every sample. Power was 67 W of 70 W, and the SM clock was 971 MHz (old: 996).
- The single client process used **9 % of one core** (max 14 %). The VM was 9 % busy.
- The engine held 62.6 of 64 requests running over the full window. It processed 1,210 prompt tok/s next to 612
  output tok/s (run window), the same split as the old server log (1,150–1,430 prompt, ~600 generation).

The client had ~10× headroom, so the old number was set by the GPU doing prefill + decode at batch 64.

### KV usage at 64 users: mean vs peak

The 0.107 and the 13 % describe the same run.

| window | KV usage mean | KV usage max |
|---|---:|---:|
| F1b replay, run window (first send → last finish) | **0.106** | **0.129** |
| F1b replay, full window (running ≥ 58) | 0.117 | 0.129 |
| old sweep, run window (ridge.md Task 0) | 0.107 | 0.129 |

So **0.107 is the run-window mean and 13 % (0.129) is the peak**. The 10–12.7 % in the old server log are 10 s
averages.

## Predicted vs measured

| Prediction | Measured | Verdict |
|---|---|---|
| F1a: output 1,100–1,400 tok/s, below the offline 1,459 | **1,464.5** (server, run window), 1,471.2 (harness); offline 1,458.6 | **wrong**: HTTP matched offline (+0.4 %) and is above the predicted range |
| F1a: client CPU the likely limiter on 4 vCPUs | 4 client processes ~7 % of one core each (28 % together), VM 14 % busy, GPU 100 % at the power cap | **wrong**: the GPU was the limit, not the client |
| F1b: within ±10 % of 615 tok/s | **610.1** (−0.9 %) | as predicted |
| F1b: util.gpu ≈ 100 % | 100.0 % mean, 100 % in every sample | as predicted |
| F1b: client CPU well below saturation → GPU-limited | client 9 % of one core (max 14 %) | as predicted |
| F1c: max-num-batched-tokens 8,192 changes output < 10 % | not run (F1 budget) | untested |

## Does NOT show

- The offline ceiling it is compared with comes from another Kaggle session (Build 14). There was no same-session
  offline run at 384. Offline sampling is temperature 1.0, HTTP is 0.
- F1c (max-num-batched-tokens 8,192 on the old workload) and a 1-process client at 384 users did not run. So this run
  does not show how many streams one harness process can drive.
- One run per point, no spread. One model (Qwen2.5-3B FP16), one T4, one session.
- NVML util.gpu (a kernel was running), not SM occupancy. CPU % is psutil per process tree at 1 Hz.
- `vllm serve` called directly, no gateway in the path.
