"""Multi-step task driver with per-task token budgets (Part C). Policies run in the client; no gateway.

    python -m benchmarks.task_budget.driver --strong http://127.0.0.1:8000=Qwen/Qwen2.5-3B-Instruct-AWQ \
        --cheap http://127.0.0.1:8001=Qwen/Qwen2.5-0.5B-Instruct --out results.jsonl [--policies baseline] [--budget N]

Task: one GSM8K problem, 3 steps, one streamed /v1/chat/completions call per attempt (checkers.py):
    1 extract the quantities as JSON   2 one arithmetic expression over them   3 state the final number
A step whose checker fails is retried up to `max_retries` times, with the failed reply and the reason appended;
retries spend budget. Step 3 retries on format failure only (checkers.py).

Token accounting: every call asks for `stream_options: {include_usage, continuous_usage_stats}` (vLLM 0.31.0
`StreamOptions`, vllm/entrypoints/generate/base/protocol.py:268), so every chunk carries the cumulative
prompt_tokens / completion_tokens of that call. Tokens of a call = prompt + completion from the last usage seen;
tokens of a task = the sum over its calls. A cancelled call counts what the server reported up to the cancel.

Policies (budget B = tokens per task, prompt + completion):
    baseline   strong pool, no budget
    hard_cut   strong pool; abort the task when its tokens reach B, cancelling the in-flight stream
    downgrade  strong pool; once remaining budget < 30 % of B, every later call goes to the cheap pool (no abort)
    escalate_fresh (alias: escalate)
               every step starts on the cheap pool; a step moves to the strong pool only after its checker failed
               on the cheap pool; abort at B like hard_cut (the same budget as policies 2-3). The strong pool gets a
               FRESH prompt for that step: the problem plus the accepted outputs of earlier steps, never the cheap
               pool's failed reply (its own failed strong attempts are carried, as in every other retry)
    escalate_carry
               the Build 14 escalate: the same, but the strong pool's prompt carries the cheap pool's failed reply
               and the checker's reason (the plain retry context)
Cancelling a stream frees the server slot only where that was measured (task_budget.md, Task 7).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks.task_budget import checkers

TASKS = Path(__file__).with_name("gsm8k_test_150.jsonl")
POLICIES = ("baseline", "hard_cut", "downgrade", "escalate_fresh", "escalate_carry")
ESCALATE = ("escalate", "escalate_fresh", "escalate_carry")
F4_POLICIES = ("baseline", "escalate_fresh", "escalate_carry")   # the follow-up run (task_budget.md, F4)
SYSTEM = "You are a careful assistant that solves grade-school math word problems step by step, following the requested format exactly."
MAX_TOKENS = {1: 256, 2: 128, 3: 384}


@dataclass
class Pool:
    name: str
    base_url: str
    model: str


@dataclass
class CallResult:
    text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_seen: bool = False
    content_chunks: int = 0
    cancelled: bool = False
    finish_reason: str | None = None
    status: int | None = None
    error: str | None = None
    ttft_s: float | None = None
    e2e_s: float | None = None

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# ---------------------------------------------------------------- prompts

def step_prompt(step: int, task: dict, ctx: dict) -> str:
    q = task["question"]
    if step == 1:
        return (f"Problem: {q}\n\nList every quantity stated in the problem that is needed to solve it. Reply with only a "
                'JSON object of the form {"quantities": [{"name": "<snake_case_name>", "value": <number>}]} and nothing else. '
                "Use plain numbers for values (no units, no percent signs, no strings).")
    qs = json.dumps({"quantities": [{"name": k, "value": v} for k, v in ctx["quantities"].items()]})
    if step == 2:
        return (f"Problem: {q}\n\nQuantities: {qs}\n\nWrite one arithmetic expression that computes the answer to the problem, "
                "using only these quantity names, numbers, + - * / and parentheses. Reply with only the expression on one line.")
    return (f"Problem: {q}\n\nQuantities: {qs}\nExpression: {ctx['expression']}\n\nCompute the answer to the problem. "
            "Think briefly if needed, then end your reply with a line of the form 'Answer: <number>'.")


def messages_for(step: int, task: dict, ctx: dict, attempts: list[dict]) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": step_prompt(step, task, ctx)}]
    for a in attempts:   # earlier failed attempts of this step: their reply and why it failed
        msgs += [{"role": "assistant", "content": a["text"]},
                 {"role": "user", "content": f"That reply failed the check: {a['check_reason']}. Reply again, following the format exactly."}]
    return msgs


def check_step(step: int, text: str, ctx: dict) -> checkers.Check:
    if step == 1:
        return checkers.check_quantities(text)
    if step == 2:
        return checkers.check_expression(text, ctx["quantities"])
    return checkers.check_answer_format(text)


# ---------------------------------------------------------------- one streamed call

def apply_chunk(res: CallResult, chunk: dict, now: float, t0: float) -> None:
    """Fold one parsed SSE chunk into the call's text and token counts (pure; unit-tested)."""
    usage = chunk.get("usage")
    if usage:
        res.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        res.completion_tokens = int(usage.get("completion_tokens") or 0)
        res.usage_seen = True
    for ch in chunk.get("choices") or []:
        piece = (ch.get("delta") or {}).get("content")
        if piece:
            if res.ttft_s is None:
                res.ttft_s = round(now - t0, 4)
            res.content_chunks += 1
            res.text += piece
        if ch.get("finish_reason"):
            res.finish_reason = ch["finish_reason"]


async def stream_call(client, pool: Pool, messages: list[dict], max_tokens: int, limit: int | None = None) -> CallResult:
    """One streamed chat call. With `limit`, the stream is closed (request cancelled) as soon as this call's
    prompt + completion tokens reach `limit`."""
    import httpx
    body = {"model": pool.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.0, "stream": True,
            "stream_options": {"include_usage": True, "continuous_usage_stats": True}}
    res = CallResult()
    t0 = time.perf_counter()
    try:
        async with client.stream("POST", pool.base_url + "/v1/chat/completions", json=body, timeout=600) as r:
            res.status = r.status_code
            if r.status_code != 200:
                res.error = (await r.aread()).decode(errors="replace")[:300]
                return res
            async for line in r.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                apply_chunk(res, json.loads(line[6:]), time.perf_counter(), t0)
                if limit is not None and res.tokens >= limit and res.finish_reason is None:
                    res.cancelled = True
                    break   # leaving the context manager closes the connection: the server sees a disconnect
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        res.error = f"{type(exc).__name__}: {exc}"[:300]
    res.e2e_s = round(time.perf_counter() - t0, 4)
    return res


# ---------------------------------------------------------------- one task under one policy

@dataclass
class Policy:
    name: str
    budget: int | None = None
    downgrade_at: float = 0.30
    max_retries: int = 2

    @property
    def cuts(self) -> bool:
        return self.name == "hard_cut" or self.name in ESCALATE

    @property
    def fresh(self) -> bool:
        return self.name in ("escalate", "escalate_fresh")

    def context_attempts(self, step_attempts: list[dict], pool: str) -> list[dict]:
        """The earlier failed attempts of this step that go into the next prompt. Fresh escalation drops the cheap
        pool's failed replies from a strong-pool prompt; everything else carries them all."""
        if self.fresh and pool == "strong":
            return [a for a in step_attempts if a["pool"] != "cheap"]
        return step_attempts

    def pool_for(self, step_attempts: list[dict], spent: int) -> str:
        if self.name in ESCALATE:
            return "strong" if any(a["pool"] == "cheap" and not a["check_ok"] for a in step_attempts) else "cheap"
        if self.name == "downgrade" and self.budget is not None and (self.budget - spent) < self.downgrade_at * self.budget:
            return "cheap"
        return "strong"


async def run_task(client, task: dict, policy: Policy, pools: dict[str, Pool]) -> dict:
    t0 = time.time()
    spent, ctx, steps = 0, {}, []
    aborted, final_value, reached = False, None, 0
    for step in (1, 2, 3):
        attempts: list[dict] = []
        passed = False
        for _ in range(1 + policy.max_retries):
            if policy.cuts and policy.budget is not None and spent >= policy.budget:
                aborted = True
                break
            pool = policy.pool_for(attempts, spent)
            limit = policy.budget - spent if policy.cuts and policy.budget is not None else None
            carried = policy.context_attempts(attempts, pool)
            res = await stream_call(client, pools[pool], messages_for(step, task, ctx, carried), MAX_TOKENS[step], limit)
            spent += res.tokens
            chk = check_step(step, res.text, ctx) if not res.cancelled and not res.error else checkers.Check(False, res.error or "cancelled at budget")
            attempts.append({"pool": pool, "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens,
                             "usage_seen": res.usage_seen, "content_chunks": res.content_chunks, "cancelled": res.cancelled,
                             "finish_reason": res.finish_reason, "status": res.status, "error": res.error,
                             "ttft_s": res.ttft_s, "e2e_s": res.e2e_s, "check_ok": chk.ok, "check_reason": chk.reason,
                             "carried_attempts": len(carried), "text": res.text})
            if res.cancelled:
                aborted = True
                break
            if chk.ok:
                passed = True
                if step == 1:
                    ctx["quantities"] = chk.value
                elif step == 2:
                    ctx["expression"] = checkers.extract_expression(res.text)
                    ctx["expression_value"] = chk.value
                else:
                    final_value = chk.value
                break
        steps.append({"step": step, "passed": passed, "retries": max(0, len(attempts) - 1),
                      "pools": [a["pool"] for a in attempts],
                      "tokens": sum(a["prompt_tokens"] + a["completion_tokens"] for a in attempts),
                      "prompt_tokens": sum(a["prompt_tokens"] for a in attempts),
                      "completion_tokens": sum(a["completion_tokens"] for a in attempts),
                      "tokens_cum": spent, "attempts": attempts})
        reached = step
        if aborted or not passed:
            break
    success = reached == 3 and steps[-1]["passed"] and checkers.final_success(final_value, task["gold"])
    return {"task_id": task["id"], "policy": policy.name, "budget": policy.budget, "success": success, "aborted": aborted,
            "failed_step": None if success else reached,
            "final_value": final_value, "gold": task["gold"], "expression_value": ctx.get("expression_value"),
            "tokens": spent, "wall_s": round(time.time() - t0, 3), "t_start_unix": round(t0, 3), "steps": steps}


# ---------------------------------------------------------------- batches

def load_tasks(path: Path = TASKS, limit: int | None = None) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return rows[:limit] if limit else rows


def batch_plan(n_tasks: int, batch: int, policies: list[str], seed: int) -> list[tuple[int, list[str]]]:
    """[(batch start index, policy order)], one random policy order per batch of `batch` tasks."""
    rng = random.Random(seed)
    plan = []
    for b in range(0, n_tasks, batch):
        order = list(policies)
        rng.shuffle(order)
        plan.append((b, order))
    return plan


async def run_batches(tasks: list[dict], policies: list[Policy], pools: dict[str, Pool], out: Path, batch: int = 8,
                      seed: int = 10, phase: str = "", deadline_unix: float | None = None) -> list[dict]:
    """For each batch of `batch` tasks, every policy in a per-batch random order; the tasks of one (batch, policy)
    run concurrently, so `batch` tasks are in flight at a time. Appends one JSON line per task to `out`."""
    import httpx
    by_name = {p.name: p for p in policies}
    rows: list[dict] = []
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=4 * batch)) as client:
        for b, order in batch_plan(len(tasks), batch, [p.name for p in policies], seed):
            for pos, name in enumerate(order):
                if deadline_unix and time.time() > deadline_unix:
                    return rows
                group = tasks[b:b + batch]
                res = await asyncio.gather(*(run_task(client, t, by_name[name], pools) for t in group))
                with open(out, "a") as f:
                    for r in res:
                        r |= {"phase": phase, "batch": b // batch, "order_pos": pos, "policy_order": order}
                        f.write(json.dumps(r) + "\n")
                rows.extend(res)
    return rows


def p75(values: list[int]) -> int:
    """75th percentile, nearest-rank (an integer token count that appears in the data)."""
    import math
    s = sorted(values)
    return s[max(0, math.ceil(0.75 * len(s)) - 1)]


def parse_pool(name: str, spec: str) -> Pool:
    url, _, model = spec.partition("=")
    return Pool(name, url.rstrip("/"), model)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strong", required=True, help="URL=model")
    ap.add_argument("--cheap", required=True, help="URL=model")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--policies", default=",".join(POLICIES))
    ap.add_argument("--budget", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=8)
    a = ap.parse_args()
    pools = {"strong": parse_pool("strong", a.strong), "cheap": parse_pool("cheap", a.cheap)}
    pols = [Policy(n, None if n == "baseline" else a.budget) for n in a.policies.split(",")]
    rows = asyncio.run(run_batches(load_tasks(limit=a.limit), pols, pools, a.out, a.batch))
    for n in a.policies.split(","):
        rs = [r for r in rows if r["policy"] == n]
        print(n, f"success {sum(r['success'] for r in rs)}/{len(rs)}", f"tokens {sum(r['tokens'] for r in rs)}")


if __name__ == "__main__":
    main()
