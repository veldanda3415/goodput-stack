# Live "tokens per completed task" — metric definition (file only; not deployed)

The task driver (`benchmarks/task_budget/driver.py`) knows, per task, every call's prompt and completion tokens (from
the streamed `usage`), the pool each call went to and the task's outcome. A deployment would export two counters from
the component that owns the task (the client or an agent runtime; a gateway only sees single calls, not tasks):

```
# HELP task_tokens_total Tokens (prompt + completion) spent by tasks, counted when the task ends.
# TYPE task_tokens_total counter
task_tokens_total{policy="hard_cut",pool="strong",kind="completion",outcome="success"} 51234
# HELP tasks_finished_total Tasks that ended, by outcome (success | failed | aborted).
# TYPE tasks_finished_total counter
tasks_finished_total{policy="hard_cut",outcome="success"} 97
```

Labels: `policy` (baseline, hard_cut, downgrade, escalate), `pool` (strong, cheap), `kind` (prompt, completion),
`outcome` (success, failed, aborted). Cardinality: 4 × 2 × 2 × 3 = 48 series for tokens, 12 for tasks.

Recording rule and panel query — tokens per completed (successful) task over the last 15 minutes, per policy:

```promql
sum by (policy) (increase(task_tokens_total[15m]))
  /
sum by (policy) (increase(tasks_finished_total{outcome="success"}[15m]))
```

The numerator counts the tokens of **all** tasks (failed and aborted ones too), so the ratio is the cost of one success,
the same definition as `tokens per SUCCESSFUL task` in [task_budget.md](../../results/t4/task_budget.md). Counting at
task end means a long task shows up late; that is the price of attributing tokens to an outcome.
Panel JSON: [grafana-panel-tokens-per-completed-task.json](grafana-panel-tokens-per-completed-task.json).
