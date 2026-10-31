# Cost per completed task under token budgets (Kaggle T4, real; policy in client; gateway not exercised)

Part C of the T4 ridge work. The question (from a LinkedIn thread): multi-step tasks that look identical from outside
can end in opposite places, and a per-step check may not tell drift from a hard step that is about to pay off.
Measured here: tokens (and dollars, where they can be attributed) per **successful** task under four budget policies,
and how early, if at all, per-step signals separate eventual successes from failures.

Code: [benchmarks/task_budget/](../../task_budget/) (driver, checkers, restricted evaluator, unit tests, analysis);
Kaggle stage `taskbudget` in [t4_notebook.py](../../kaggle/t4_notebook.py).

## Task set and steps

- 150 problems from the GSM8K **test** split (`openai/gsm8k`, config `main`, dataset repo sha `740312ad…` on
  2026-10-31, rows fetched with the HF datasets-server rows API), chosen with `random.Random(0).sample` over all 1,319
  test indices: [gsm8k_test_150.jsonl](../../task_budget/gsm8k_test_150.jsonl) (sha256 `3d813312…cbc802624`),
  built by [make_taskset.py](../../task_budget/make_taskset.py). IDs (test-split row index):
  2, 28, 33, 44, 54, 67, 74, 79, 82, 92, 127, 128, 141, 151, 164, 168, 183, 186, 187, 191, 194, 202, 206, 223, 236, 237,
  239, 245, 253, 254, 255, 266, 285, 286, 291, 299, 300, 306, 349, 376, 378, 382, 386, 387, 389, 391, 398, 416, 418, 440,
  447, 448, 451, 454, 482, 488, 495, 497, 499, 513, 530, 532, 533, 555, 563, 564, 577, 589, 594, 596, 617, 621, 635, 647,
  649, 655, 664, 666, 676, 681, 682, 686, 724, 731, 733, 758, 761, 788, 801, 816, 829, 858, 861, 872, 889, 906, 911, 917,
  922, 966, 975, 976, 981, 995, 996, 1002, 1008, 1010, 1033, 1040, 1047, 1067, 1068, 1074, 1090, 1094, 1106, 1107, 1112,
  1120, 1121, 1123, 1128, 1131, 1146, 1162, 1175, 1178, 1179, 1187, 1194, 1202, 1203, 1207, 1221, 1232, 1233, 1235, 1240,
  1241, 1251, 1253, 1254, 1266, 1280, 1290, 1298, 1300, 1311, 1313.
- Each task = 3 steps, each step one streamed `/v1/chat/completions` call (temperature 0) with its own checker:
  1. extract the quantities as JSON `{"quantities": [{"name": <identifier>, "value": <number>}]}` → valid JSON + schema;
  2. one arithmetic expression over those names → parses and evaluates in a restricted AST evaluator (no `eval`);
  3. state the final number (`Answer: <number>`) → format check; **final success** = exact numeric match with GSM8K.
- A step that fails its checker is retried up to 2 times (the failed reply and the reason are appended); retries spend budget.
- Tokens = prompt + completion of every call, read from the stream (`stream_options: include_usage + continuous_usage_stats`,
  so a cancelled call still has exact counts up to the cancel), summed per task.

## Predictions (written before Task 10, verbatim from the assignment, plus the stated thresholds)

Pools: strong = Qwen2.5-3B-Instruct-AWQ, cheap = Qwen/Qwen2.5-0.5B-Instruct FP16 (record revision), both on one T4 as two instances (Part B setup; set memory fractions so both fit — compute and record them from measured weight sizes).
- Baseline success rate on the strong pool: roughly in line with the earlier gsm8k score for this model (0.62 flexible-match at n = 250) — state it as a range, not a point.
  **Range: 0.45–0.75** (the earlier 0.624 ± 0.031 was lm-eval 5-shot without chat template; this pipeline is 3 chat
  calls with strict formats, so the range is wide on both sides).
- Hard cut lowers tokens per attempted task but raises tokens per SUCCESSFUL task only if it mostly kills tasks that would have succeeded.
- Downgrade lowers cost per attempted task; its cost per successful task depends on the cheap pool's step-3 success.
- Escalate-on-failure has the lowest cost per successful task if the cheap pool passes step 1 most of the time.
- Step-1 checker pass/fail separates eventual successes from failures only weakly (the claim under test); state what "weakly" means (e.g. AUC < 0.7) before running.
  **"Weakly" = AUC < 0.7** for step-1 first-try pass → final success on the strong-pool baseline (n = 150); "strongly"
  = AUC ≥ 0.8; in between = moderate. The 95 % bootstrap interval is reported; a claim needs the whole interval on one side.

## Decisions made

- **Step 3 retries on format only.** The assignment's step-3 checker is the exact match with the GSM8K answer. Retrying
  on that check would give the policy the answer key, which no production checker has, and turn final success into
  "right within 3 guesses". So step 3 is retried only when no `Answer: <number>` line is found; a wrong number ends the
  task as a failure.
- **Budget source and order.** The budget comes from the baseline (75th percentile of tokens per successful task), so a
  first full baseline pass ("calibration") runs before the others. Then all four policies, including the baseline again,
  run over the same 150 tasks with a random policy order per batch of 8 tasks (8 tasks in flight). The policy table uses
  this second pass, so no policy always runs first; the calibration pass is reported as a repeat-run check.
- **Escalate uses the budget as a hard cap** (abort at the budget, like the hard cut). The assignment gives policies 2–4
  the same budget; for escalate the only use of a budget is a cap.
- **Downgrade does not abort.** It only switches pools once less than 30 % of the budget remains.
- **Token budget counts prompt + completion tokens** of all calls; the step prompts repeat the problem, so prompt tokens
  are a large share.

## Pools and memory fractions (computed before Task 10 from measured weight sizes)

| pool | model @ revision | weights (measured) | KV bytes/token (config.json) | `--gpu-memory-utilization` | KV pool CALCULATED |
|---|---|---:|---:|---:|---:|
| strong | `Qwen/Qwen2.5-3B-Instruct-AWQ` @ `3559b226e8ce77211e2c1bd7ddfb7686fec4d6dd` | 1.95 GiB (run 20261031-085014_twoinst) | 36,864 | **0.50** | (14.56 × 0.50 − 1.95 − 0.85) GiB ÷ 36,864 B ≈ 130,500 tokens |
| cheap | `Qwen/Qwen2.5-0.5B-Instruct` @ `7ae557604adf67be50417f59c2c2f167def9a775` | 0.93 GiB (same run) | 12,288 (2 × 24 layers × 2 KV heads × 64 × 2 B) | **0.35** | (14.56 × 0.35 − 0.93 − 0.81) GiB ÷ 12,288 B ≈ 293,300 tokens |

14.56 GiB is the total vLLM reports on this T4 (Part B over-allocation error). 0.85 / 0.81 GiB are the non-KV, non-weight
memory measured in Part B at 0.45 (3B AWQ) and 0.30 (0.5B). The strong instance starts first; the cheap one asks
for 0.35 × 14.56 = 5.10 GiB of the ≈ 7.1 GiB left, so vLLM's start-up check passes. Both pools need only a few
thousand KV tokens at 8 tasks in flight, so the split leaves headroom.

## Run (20261031-091201_taskbudget, Kaggle T4, real; policy in client; gateway not exercised)

One session, script session 1,462 s = **0.406 GPU-h**. git `61ca1f8`, Tesla T4 (GPU 0 only), driver 580.178.04,
CUDA 13.0, vLLM 0.31.0 (torch 2.13.0+cu130). Stage: `make t4-run STAGE=taskbudget ARGS='--args "--strong-util 0.50
--cheap-util 0.35 --cheap-revision 7ae55760"'`. Serve flags per pool: `--dtype half --no-enable-prefix-caching
--gpu-memory-utilization {0.50 | 0.35} --revision <sha>`, everything else default. Startup: strong weights 1.95 GiB,
KV 4.03 GiB = **117,408 tokens** (CALCULATED ≈ 130,500); cheap weights 0.93 GiB, KV 3.35 GiB = **293,040 tokens**
(CALCULATED ≈ 293,300). `nvidia-smi --query-compute-apps`: 7,088 MiB + 5,134 MiB. Both warmed with 8 concurrent
discarded tasks each. Client: driver in the kernel, temperature 0, `max_tokens` 256 / 128 / 384 for steps 1 / 2 / 3,
8 tasks in flight. Order: calibration baseline (150 tasks, 180 s), then 600 task runs (4 policies × 150, 607 s), with a
random policy order per batch of 8 tasks (seed 11): baseline ran first in 3 of 19 batches, hard_cut in 7, downgrade in
2, escalate in 7 (the last batch has 6 tasks).

## Task 7 — does vLLM free a cancelled stream? (vLLM 0.31.0, called directly)

`cancel_probe`: one streamed chat request (`ignore_eos`, `max_tokens` 2,000, temperature 0), client disconnects 3.0 s
after sending, `/metrics` scraped every 0.25 s from 1 s before the request to 15 s after the disconnect; n = 3 per pool,
both pools up, no other load. Raw metric lines per sample are in the `cancel-*` rows.

| pool | trial | tokens received before disconnect (usage) | last sample before disconnect: running / KV usage | first sample after disconnect | freed after | at +15 s |
|---|---:|---|---|---|---:|---|
| strong (3B AWQ) | 0 | 48 prompt + 252 completion | 1 / 0.00259 | running 0, KV 0.0 | **0.155 s** | running 0, KV 0.0 |
| strong | 1 | 48 + 245 | 1 / 0.00245 | running 0, KV 0.0 | **0.147 s** | 0 / 0.0 |
| strong | 2 | 48 + 242 | 1 / 0.00245 | running 0, KV 0.0 | **0.146 s** | 0 / 0.0 |
| cheap (0.5B) | 0 | 48 + 503 | 1 / 0.00186 | running 0, KV 0.0 | **0.167 s** | 0 / 0.0 |
| cheap | 1 | 48 + 502 | 1 / 0.00186 | running 0, KV 0.0 | **0.173 s** | 0 / 0.0 |
| cheap | 2 | 48 + 500 | 1 / 0.00186 | running 0, KV 0.0 | **0.170 s** | 0 / 0.0 |

**vLLM 0.31.0 frees the sequence and its KV blocks on a streaming client disconnect, 6/6, at the first scrape after the
disconnect (≤ 0.17 s; the 0.25 s sampling is the resolution).** `vllm:request_success_total{finished_reason="abort"}`
stayed **0.0** in every trial: the cancelled request is not counted in that counter, so it cannot be used to count cancellations.

Known for the other engines (not re-measured here; [GAPS P3](../../../deploy/gateway/GAPS.md#p3--does-a-client-disconnect-free-the-engine-slot)):
llama.cpp called directly frees a streamed slot after ~1.5 s; **through agentgateway it is not freed within 15 s**
(issue #19); non-streamed requests are never freed; llm-d-inference-sim never cancels on disconnect (SIMULATED).
So "cut" policies are valid here (vLLM, direct, streamed). They would not free capacity behind agentgateway, and they are
untestable on the simulator.

## Task 10/11 — results

Budget = **951 tokens** per task: 75th percentile (nearest rank) of tokens per successful task in the calibration
baseline (95 / 150 successes). Policy table: the 600 randomized-order runs.

| policy | success | abort | **tokens per SUCCESSFUL task** | tokens per attempted task | mean tokens of a successful task | tokens wasted on aborted tasks | tokens strong / cheap pool | task wall p50 / p95 s | $ per successful task CALCULATED |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| baseline | **94 / 150 (0.627)** | 0 | **1,566** | 981 | 896 | 0 | 147,205 / 0 | 6.26 / 8.84 | 0.000311 |
| hard_cut | 72 / 150 (0.480) | 52 (0.347) | **1,818** | 873 | 795 | 51,798 | 130,889 / 0 | 5.65 / 7.52 | 0.000341 |
| downgrade | 92 / 150 (0.613) | 0 | **1,588** | 974 | 870 | 0 | 130,269 / 15,858 | 6.45 / 10.51 | 0.000339 |
| escalate | 4 / 150 (0.027) | 97 (0.647) | **36,079** | 962 | 677 | 103,928 | 74,877 / 69,440 | 4.85 / 6.38 | 0.006570 |

Tokens = prompt + completion of every call. Chart: [charts/task_budget_cost_per_success.png](charts/task_budget_cost_per_success.png).
Analysis: [analysis.json](20261031-091201_taskbudget/results/taskbudget/analysis.json)
(`python -m benchmarks.task_budget.analyze benchmarks/results/t4/20261031-091201_taskbudget`). Raw task records
(task ID, policy, pool per attempt, tokens per step, checker result and reply per attempt, retries, success, wall time):
[tasks.jsonl](20261031-091201_taskbudget/results/taskbudget/tasks.jsonl).

**Dollars (CALCULATED, secondary).** Per policy, GPU-seconds = completion tokens on a pool ÷ that pool's output tok/s
while it had a request running in the policy phase (strong 236.4 tok/s over 597.6 s busy, cheap 143.2 tok/s over 164.0 s
busy; `vllm:generation_tokens_total` deltas), × $0.526/h (Azure NC4as_T4_v3, the repo's cited price), ÷ successes.
**Caveat:** the two pools share one GPU and were busy at the same time for ≥ 154 s of the 607 s phase, and each pool's
busy time is charged at the full GPU price, so the overlap is double-counted (up to +27 %). Prompt tokens are not
charged separately. Tokens per successful task is the primary metric.

What happened per policy:

- **baseline** — 94 successes; failures: 48 wrong final number (step 3), 7 at step 2, 1 at step 1. The calibration pass
  gave 95; 149 of 150 tasks had the same outcome in both passes.
- **hard_cut** — aborted 52 tasks, 41 of them cut in flight during step 3's first attempt (the step that costs most,
  511 tokens mean in the baseline). **23 of the 52 cut tasks succeeded in the baseline.** It saved 11 % of all tokens
  (130,889 vs 147,205) but lost 23 % of the successes, so tokens per success went **up 16 %** (1,566 → 1,818).
- **downgrade** — 20 tasks crossed 70 % of the budget and finished on the cheap pool; 92 successes. Practically the
  baseline: −1 % tokens per attempted task, +1 % per success.
- **escalate** — the cheap 0.5B passed step 1 on the first try in **34 / 150** tasks (strong: 148 / 150). On a failure the
  step moves to the strong pool **with the cheap model's failed reply and the checker's reason in its context** (the
  retry design), and the strong model often repeated the cheap model's mistake (task 2: both replies named a quantity
  `"House cost"`, not an identifier). Two failed attempts and a third prompt that carries both exceed the 951-token cap: 49
  tasks were cut at step 1, 13 at step 2, 35 at step 3; 57 of the 97 cut tasks succeeded in the baseline. 4 successes,
  36,079 tokens per success.

### Early signals: do per-step checks predict the outcome?

Strong-pool baseline, policy pass (n = 150, 94 successes). AUC = P(signal of a random success > signal of a random
failure); 95 % CI from 2,000 bootstrap resamples. 2×2 = step-k checker passed on the first try × final success.

| signal | 2×2: pass & success / pass & fail / fail & success / fail & fail | AUC (95 % CI) |
|---|---|---|
| step 1 first-try pass | 93 / 55 / 1 / 1 | **0.504 (0.485 … 0.526)** |
| step 1 passed (after retries) | 94 / 55 / 0 / 1 | 0.509 (0.500 … 0.531) |
| tokens used after step 1 (fewer = higher) | — | 0.570 (0.472 … 0.671) |
| step 2 first-try pass | 93 / 46 / 1 / 10 | **0.584 (0.536 … 0.638)** |
| step 2 passed (after retries) | 94 / 48 / 0 / 8 | 0.571 (0.528 … 0.621) |
| tokens used after step 2 | — | 0.654 (0.565 … 0.747) |
| tokens after step 2, only tasks whose step 2 passed first try (n = 139) | — | 0.587 (0.486 … 0.682) |

The calibration pass gives the same picture (step 1 first try 0.504, 0.485 … 0.527; step 2 first try 0.586, 0.537 …
0.640; tokens after step 2 0.657, 0.568 … 0.752).

**Three pairs that looked identical after step 1 and ended in opposite outcomes** (both passed step 1 on the first
try on the strong pool with the same token count; `example_pairs` in analysis.json has the replies):

| pair | success | failure |
|---|---|---|
| 1 | **task 44** (gold 20): step 1 ok, 270 tok; step 2 ok, expression evaluates to **380** (wrong); step 3 recomputes from the problem and answers **20** ✓ (1,083 tok) | **task 389** (gold 6): step 1 ok, 270 tok; step 2 ok, `30-(30+18)` = −18; step 3 answers **−18** ✗ (1,058 tok) |
| 2 | **task 54** (gold 40): step 1 ok, 238 tok; step 2 `7.0 + 21.0 + 12.0` = 40; step 3 answers 40 ✓ (793 tok) | **task 1146** (gold 16): step 1 ok, 238 tok; step 2 ok, expression = 180; step 3 answers **180** ✗ (1,067 tok) |
| 3 | **task 92** (gold 4): step 1 ok, 215 tok; step 2 ok, expression = **17** (wrong); step 3 answers **4** ✓ (892 tok) | **task 495** (gold 200): step 1 ok, 215 tok; step 2 fails 3 times (quoted JSON paths, `"quantities.hours_per_day.value" * …`), task ends at 1,262 tok ✗ |

Two of the three successes went through a **wrong** intermediate expression that the step-2 checker accepted (it can
only check that the expression parses and evaluates), and step 3 recovered. A per-step check that passes does not mean
the chain is on track, and a later step can repair an earlier one.

**Can a per-step check tell drift from a hard step about to pay off? Not in this data.** The step-1 check passed for 148 of
150 tasks, successes and failures alike (AUC 0.504, CI 0.485 … 0.526). The step-2 check and tokens-so-far are only weak
signals (AUC 0.58 and 0.65, upper CI bounds 0.64 and 0.75). The checks catch format failures, not wrong reasoning.

## Predicted vs measured

| Prediction | Measured | Verdict |
|---|---|---|
| Baseline success 0.45–0.75 | **0.627** (94/150; calibration 0.633) | inside the range; close to the earlier lm-eval 0.624 for this model |
| Hard cut lowers tokens per attempted task; raises tokens per success only if it mostly kills would-be successes | per attempted 981 → **873** (lower); per success 1,566 → **1,818** (higher), while only **23 of 52** cut tasks (44 %) were would-be successes | first half holds. Second half **wrong**: tokens per success rose without the cut killing *mostly* would-be successes. Cutting 44 % would-be successes already loses more successes (−23 %) than tokens (−11 %) |
| Downgrade lowers cost per attempted task; per success depends on the cheap pool's step-3 success | per attempted 981 → 974 (−0.7 %); per success +1.4 %; only 20 tasks reached the cheap pool, which passed the step-3 format on 9 of 14 attempts | small effect in both directions; at this budget, downgrade barely triggers |
| Escalate has the lowest cost per success *if* the cheap pool passes step 1 most of the time | the condition failed (cheap step-1 first-try pass 34/150 = 23 %); escalate had the **highest** cost per success (36,079) | the condition was false, and the result is the opposite. The retry context carrying the cheap reply and the hard cap made it worse |
| Step-1 pass separates eventual outcomes only weakly (AUC < 0.7) | **0.504 (0.485 … 0.526)** | **weak**, as predicted, with the whole CI below 0.7 (and near 0.5: step 1 almost always passes) |

## Does NOT show

- One task type (3-step GSM8K arithmetic), GSM8K only, 150 tasks, one run per policy (plus one calibration baseline).
- **Policy in the client, gateway not exercised.** Behind agentgateway a cancel does not free the engine slot (P3), so
  the hard cut there would save client-side tokens but not GPU work.
- Two small models (3B AWQ, 0.5B FP16) sharing one T4; the cheap pool is much weaker than the strong one at step 1.
- The escalate result depends on the retry design (failed replies carried into the next attempt) and on the cap at the
  same budget; a fresh-context escalation was not measured.
- Dollar figures are CALCULATED with an attribution that double-counts overlapping pool time; not a bill.
- No live migration: a decode in flight is never moved between pods (its KV stays on the pod), and nothing here claims it.

## F4 — escalate with a fresh context (follow-up)

### Predictions (written before the F4 run, verbatim from the assignment)

escalate_fresh success close to baseline (within ~10 points); tokens per successful task at or above baseline, because the cheap pool passes step 1 first try in only ~34/150 tasks so most steps escalate anyway; escalate_carry reproduces Build 14's very low success.
