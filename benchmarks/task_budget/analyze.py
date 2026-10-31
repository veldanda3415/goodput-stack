"""Part C analysis: cost per completed task by policy, early-signal AUCs, example pairs, chart.

    python -m benchmarks.task_budget.analyze benchmarks/results/t4/<run>_taskbudget [--price-per-h 0.526]

Reads results/taskbudget/{tasks.jsonl, taskbudget.jsonl, metrics.jsonl}. Writes analysis.json and
cost_per_success.png next to them and prints markdown tables. Only the `policies` phase (all four policies, random
order per batch) enters the policy table; the `calibration` baseline only sets the budget and is reported as a
repeat-run check.

Definitions (all tokens = prompt + completion, every call, retries included):
    tokens per attempted task   = total tokens of the policy's 150 task runs / 150
    tokens per SUCCESSFUL task  = total tokens of the policy's 150 task runs / number of successes (cost of one success)
    wasted on aborted tasks     = total tokens of task runs that the budget cut
    AUC                         = P(score of a random eventual success > score of a random failure), ties count 1/2;
                                  95 % CI from 2,000 bootstrap resamples of tasks (seed 0)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path

POLICIES = ("baseline", "hard_cut", "downgrade", "escalate", "escalate_fresh", "escalate_carry")


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def auc(scores: list[float], labels: list[bool]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def auc_ci(scores: list[float], labels: list[bool], n_boot: int = 2000, seed: int = 0) -> tuple[float | None, float | None, float | None]:
    point = auc(scores, labels)
    rng = random.Random(seed)
    idx = list(range(len(scores)))
    boots = []
    for _ in range(n_boot):
        pick = [rng.choice(idx) for _ in idx]
        a = auc([scores[i] for i in pick], [labels[i] for i in pick])
        if a is not None:
            boots.append(a)
    return point, pct(boots, 2.5), pct(boots, 97.5)


def pool_tokens(r: dict) -> dict:
    out = {"strong": {"prompt": 0, "completion": 0}, "cheap": {"prompt": 0, "completion": 0}}
    for s in r["steps"]:
        for a in s["attempts"]:
            out[a["pool"]]["prompt"] += a["prompt_tokens"]
            out[a["pool"]]["completion"] += a["completion_tokens"]
    return out


def first_try(r: dict, step: int) -> bool:
    s = next((s for s in r["steps"] if s["step"] == step), None)
    return bool(s and s["attempts"] and s["attempts"][0]["check_ok"])


def passed(r: dict, step: int) -> bool:
    s = next((s for s in r["steps"] if s["step"] == step), None)
    return bool(s and s["passed"])


def tokens_after(r: dict, step: int) -> int:
    s = next((s for s in r["steps"] if s["step"] == step), None)
    return s["tokens_cum"] if s else r["tokens"]


def pool_rates(metrics: list[dict], t0: float, t1: float) -> dict:
    """Per pool: output tokens per second of the time that pool had >= 1 running request, in [t0, t1]."""
    out = {}
    for pool in ("strong", "cheap"):
        ms = [m for m in metrics if m.get("server") == pool and "metrics" in m and t0 <= m["t_unix"] <= t1]
        busy_s, gen = 0.0, 0.0
        for a, b in zip(ms, ms[1:]):
            dg = b["metrics"].get("generation_tokens_total", 0) - a["metrics"].get("generation_tokens_total", 0)
            if a["metrics"].get("num_requests_running", 0) > 0 or b["metrics"].get("num_requests_running", 0) > 0 or dg > 0:
                busy_s += b["t_unix"] - a["t_unix"]
                gen += dg
        out[pool] = {"busy_s": round(busy_s, 1), "generation_tokens": gen,
                     "output_tok_s_while_busy": round(gen / busy_s, 2) if busy_s else None,
                     "window_s": round(t1 - t0, 1)}
    return out


def escalated(step: dict) -> bool:
    """A cheap-pool attempt of this step was followed by a strong-pool attempt (downgrade's strong -> cheap is not)."""
    return any(a == "cheap" and b == "strong" for a, b in zip(step["pools"], step["pools"][1:]))


def policy_table(rows: list[dict], rates: dict, price_h: float) -> list[dict]:
    table = []
    for pol in POLICIES:
        rs = [r for r in rows if r["policy"] == pol]
        if not rs:
            continue
        succ = [r for r in rs if r["success"]]
        total = sum(r["tokens"] for r in rs)
        pt = [pool_tokens(r) for r in rs]
        comp = {p: sum(x[p]["completion"] for x in pt) for p in ("strong", "cheap")}
        allt = {p: sum(x[p]["completion"] + x[p]["prompt"] for x in pt) for p in ("strong", "cheap")}
        gpu_s = {p: comp[p] / rates[p]["output_tok_s_while_busy"] if rates.get(p, {}).get("output_tok_s_while_busy") else None
                 for p in ("strong", "cheap")}
        dollars = (sum(v for v in gpu_s.values() if v) * price_h / 3600) if all(v is not None or comp[p] == 0
                                                                             for p, v in gpu_s.items()) else None
        steps = [st for r in rs for st in r["steps"]]
        atts = [a for st in steps for a in st["attempts"]]
        table.append({
            "policy": pol, "tasks": len(rs), "successes": len(succ), "success_rate": round(len(succ) / len(rs), 4),
            "aborted": sum(r["aborted"] for r in rs), "abort_rate": round(sum(r["aborted"] for r in rs) / len(rs), 4),
            "tokens_total": total, "tokens_per_attempted": round(total / len(rs), 1),
            "tokens_per_success": round(total / len(succ), 1) if succ else None,
            "mean_tokens_of_successful_tasks": round(statistics.fmean([r["tokens"] for r in succ]), 1) if succ else None,
            "tokens_wasted_aborted": sum(r["tokens"] for r in rs if r["aborted"]),
            "tokens_failed_attempts": sum(a["prompt_tokens"] + a["completion_tokens"] for a in atts if not a["check_ok"]),
            "steps_reached": len(steps), "steps_escalated": sum(escalated(st) for st in steps),
            "share_steps_escalated": round(sum(escalated(st) for st in steps) / len(steps), 4) if steps else None,
            "cheap_step1_first_try_pass": sum(1 for r in rs if r["steps"] and r["steps"][0]["attempts"][0]["pool"] == "cheap"
                                              and r["steps"][0]["attempts"][0]["check_ok"]),
            "tokens_by_pool": allt, "completion_tokens_by_pool": comp,
            "wall_p50_s": round(pct([r["wall_s"] for r in rs], 50), 2), "wall_p95_s": round(pct([r["wall_s"] for r in rs], 95), 2),
            "gpu_s_attributed_CALCULATED": {p: round(v, 2) if v else v for p, v in gpu_s.items()},
            "usd_per_success_CALCULATED": round(dollars / len(succ), 6) if dollars is not None and succ else None,
            "usd_per_attempted_CALCULATED": round(dollars / len(rs), 6) if dollars is not None else None,
        })
    return table


def early_signal(rows: list[dict]) -> dict:
    """For one policy's task runs: step-k first-try pass, step-k eventual pass, tokens after step k -> final success."""
    y = [r["success"] for r in rows]
    out: dict = {"n": len(rows), "successes": sum(y)}
    for step in (1, 2):
        ft = [first_try(r, step) for r in rows]
        ev = [passed(r, step) for r in rows]
        tk = [-tokens_after(r, step) for r in rows]   # fewer tokens so far = higher score
        def table(sig):
            return {"pass_success": sum(s and t for s, t in zip(sig, y)), "pass_fail": sum(s and not t for s, t in zip(sig, y)),
                    "fail_success": sum((not s) and t for s, t in zip(sig, y)), "fail_fail": sum((not s) and not t for s, t in zip(sig, y))}
        out[f"step{step}"] = {
            "first_try_2x2": table(ft), "first_try_auc": auc_ci([float(s) for s in ft], y),
            "eventual_2x2": table(ev), "eventual_auc": auc_ci([float(s) for s in ev], y),
            "tokens_so_far_auc": auc_ci(tk, y),
        }
        # among tasks that passed step k on the first try (the "looked fine" group): tokens so far vs outcome
        sub = [i for i, s in enumerate(ft) if s]
        out[f"step{step}"]["among_first_try_pass"] = {"n": len(sub), "successes": sum(y[i] for i in sub),
                                                     "tokens_so_far_auc": auc_ci([tk[i] for i in sub], [y[i] for i in sub])}
    return out


def example_pairs(rows: list[dict], k: int = 3) -> list[dict]:
    """Pairs that looked identical after step 1 (step 1 passed on the first try, same pool, tokens so far within 10 %)
    and ended in opposite outcomes; the k closest pairs by token difference, each task used once."""
    ok1 = [r for r in rows if first_try(r, 1) and len(r["steps"][0]["attempts"]) == 1]
    s = [r for r in ok1 if r["success"]]
    f = [r for r in ok1 if not r["success"]]
    cands = []
    for a in s:
        for b in f:
            ta, tb = tokens_after(a, 1), tokens_after(b, 1)
            if a["steps"][0]["pools"] == b["steps"][0]["pools"] and abs(ta - tb) <= 0.1 * max(ta, tb):
                cands.append((abs(ta - tb), a, b))
    cands.sort(key=lambda c: (c[0], c[1]["task_id"], c[2]["task_id"]))
    used, out = set(), []
    for d, a, b in cands:
        if a["task_id"] in used or b["task_id"] in used:
            continue
        used |= {a["task_id"], b["task_id"]}
        out.append({"token_diff_after_step1": d, "success": brief(a), "failure": brief(b)})
        if len(out) == k:
            break
    return out


def brief(r: dict) -> dict:
    return {"task_id": r["task_id"], "policy": r["policy"], "success": r["success"], "aborted": r["aborted"],
            "gold": r["gold"], "final_value": r["final_value"], "expression_value": r.get("expression_value"),
            "steps": [{"step": s["step"], "passed": s["passed"], "retries": s["retries"], "pools": s["pools"],
                       "tokens": s["tokens"], "tokens_cum": s["tokens_cum"],
                       "replies": [a["text"][:300] for a in s["attempts"]],
                       "check": [a["check_reason"] or "ok" for a in s["attempts"]]} for s in r["steps"]]}


def chart(table: list[dict], path: Path, budget: int | None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pols = [t["policy"] for t in table]
    vals = [t["tokens_per_success"] or 0 for t in table]
    att = [t["tokens_per_attempted"] for t in table]
    fig, ax = plt.subplots(figsize=(7, 4))
    x = range(len(pols))
    ax.bar([i - 0.2 for i in x], vals, width=0.4, label="tokens per successful task", color="#3b6ea5")
    ax.bar([i + 0.2 for i in x], att, width=0.4, label="tokens per attempted task", color="#a9c4e0")
    for i, t in enumerate(table):
        ax.text(i - 0.2, vals[i], f"{vals[i]:,.0f}\n{t['success_rate']:.0%} ok", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x), pols)
    ax.set_ylabel("tokens (prompt + completion)")
    ax.set_title(f"Cost per task by policy, 150 GSM8K tasks (budget {budget:,} tokens)\nKaggle T4, real; policy in client; gateway not exercised",
                 fontsize=9)
    ax.legend(fontsize=8, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylim(0, max(vals + att) * 1.25)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--price-per-h", type=float, default=0.526)
    ap.add_argument("--stage-dir", default="taskbudget", help="results/<stage-dir>/ (followup for the F4 run)")
    ap.add_argument("--phase", default="policies", help="tasks.jsonl phase that enters the policy table (f4 for the F4 run)")
    a = ap.parse_args()
    d = a.run_dir / "results" / a.stage_dir
    tasks = read_jsonl(d / "tasks.jsonl")
    meta = {r["key"]: r for r in read_jsonl(d / f"{a.stage_dir}.jsonl")}
    metrics = read_jsonl(d / "metrics.jsonl")
    pol_rows = [r for r in tasks if r.get("phase") == a.phase]
    cal_rows = [r for r in tasks if r.get("phase") == "calibration"]
    pw = meta.get(a.phase, {}).get("window_unix") or [min(r["t_start_unix"] for r in pol_rows), max(r["t_start_unix"] + r["wall_s"] for r in pol_rows)]
    rates = pool_rates(metrics, *pw)
    budget = meta.get("calibration", {}).get("budget_tokens") or meta.get(a.phase, {}).get("budget_tokens")
    table = policy_table(pol_rows, rates, a.price_per_h)
    base = [r for r in pol_rows if r["policy"] == "baseline"]
    cal_by = {r["task_id"]: r["success"] for r in cal_rows}
    repeat = {"calibration_success": sum(cal_by.values()), "policies_baseline_success": sum(r["success"] for r in base),
              "same_outcome": sum(1 for r in base if cal_by.get(r["task_id"]) == r["success"]), "n": len(base)}
    early = {"baseline": early_signal(base), **({"baseline_calibration": early_signal(cal_rows)} if cal_rows else {})}
    pairs = example_pairs(base)
    out = {"budget_tokens": budget, "pool_rates": rates, "policy_table": table, "repeat_check": repeat,
           "early_signal": early, "example_pairs": pairs, "price_per_h": a.price_per_h}
    out["phase"] = a.phase
    (d / ("analysis.json" if a.phase == "policies" else f"analysis-{a.phase}.json")).write_text(json.dumps(out, indent=1, default=str) + "\n")
    if table:
        chart(table, d / ("cost_per_success.png" if a.phase == "policies" else f"cost_per_success-{a.phase}.png"), budget or 0)
    print(json.dumps({k: v for k, v in out.items() if k != "example_pairs"}, indent=1, default=str)[:12000])


if __name__ == "__main__":
    main()
