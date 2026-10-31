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
