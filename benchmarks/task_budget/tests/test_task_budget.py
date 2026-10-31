"""Unit tests: restricted evaluator, step checkers, token accounting, policies (local, no GPU).

    .venv/bin/python -m pytest benchmarks/task_budget/tests -q
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from benchmarks.task_budget import checkers, driver
from benchmarks.task_budget.evaluator import EvalError, safe_eval
from benchmarks.task_budget.tests import fake_openai


# ---------------------------------------------------------------- evaluator

@pytest.mark.parametrize("expr,names,want", [
    ("1 + 2 * 3", {}, 7), ("(1 + 2) * 3", {}, 9), ("-a + b", {"a": 2, "b": 5}, 3), ("price * (1 + rate / 100)",
     {"price": 80000, "rate": 150}, 200000), ("7 // 2 + 7 % 2", {}, 4), ("2 ** 10", {}, 1024), ("1.5 * 4", {}, 6)])
def test_eval_ok(expr, names, want):
    assert safe_eval(expr, names) == pytest.approx(want)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('true')", "open('x')", "a.b", "x[0]", "1 if 1 else 2", "lambda: 1", "[1, 2]",
    "'a' * 3", "1 < 2", "True + 1", "9 ** 9 ** 9", "2 ** 100", "1 / 0", "unknown + 1", "1 +", "", "(" * 300 + "1" + ")" * 300,
    "10 ** 16"])
def test_eval_rejects(expr):
    with pytest.raises(EvalError):
        safe_eval(expr, {"a": 1})


# ---------------------------------------------------------------- checkers

def test_quantities_ok_and_fenced():
    text = '```json\n{"quantities": [{"name": "eggs", "value": 16}, {"name": "price", "value": 2.5}]}\n```'
    c = checkers.check_quantities(text)
    assert c.ok and c.value == {"eggs": 16.0, "price": 2.5}


@pytest.mark.parametrize("text", [
    "eggs = 16", '{"quantities": []}', '{"quantities": [{"name": "eggs", "value": "16"}]}',
    '{"quantities": [{"name": "two words", "value": 1}]}', '{"quantities": [{"name": "class", "value": 1}]}',
    '{"quantities": [{"name": "a", "value": 1, "unit": "kg"}]}', '{"quantities": [{"name": "a", "value": 1}], "x": 1}',
    '{"quantities": [{"name": "a", "value": 1}, {"name": "a", "value": 2}]}', '{"quantities": [{"name": "a", "value": true}]}'])
def test_quantities_rejects(text):
    assert not checkers.check_quantities(text).ok


@pytest.mark.parametrize("text,want", [
    ("eggs * price", 40), ("Expression: eggs * price.", 40), ("answer = eggs * price", 40), ("`eggs*price`", 40),
    ("Here it is:\neggs * price", 40)])
def test_expression_ok(text, want):
    c = checkers.check_expression(text, {"eggs": 16, "price": 2.5})
    assert c.ok and c.value == pytest.approx(want)


@pytest.mark.parametrize("text", ["eggs * cost", "print(eggs)", "", "eggs ==  2"])
def test_expression_rejects(text):
    assert not checkers.check_expression(text, {"eggs": 16}).ok


@pytest.mark.parametrize("text,want", [("So 18.\nAnswer: 18", 18), ("Answer: $1,200", 1200), ("**Answer:** 7.5", 7.5),
                                       ("Answer: 3\nAnswer: -4", -4)])
def test_answer_format(text, want):
    c = checkers.check_answer_format(text)
    assert c.ok and c.value == want


def test_answer_format_missing_and_final_success():
    assert not checkers.check_answer_format("The answer is 18").ok
    assert checkers.final_success(70000.0, "70000") and not checkers.final_success(69999.0, "70000")
    assert not checkers.final_success(None, "1")


# ---------------------------------------------------------------- token accounting

def test_apply_chunk_continuous_usage():
    res = driver.CallResult()
    chunks = [{"choices": [{"delta": {"role": "assistant", "content": ""}}], "usage": {"prompt_tokens": 40, "completion_tokens": 0}},
              {"choices": [{"delta": {"content": "Hel"}}], "usage": {"prompt_tokens": 40, "completion_tokens": 1}},
              {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 40, "completion_tokens": 2}},
              {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 2, "total_tokens": 42}}]
    for i, c in enumerate(chunks):
        driver.apply_chunk(res, c, now=1.0 + i, t0=1.0)
    assert (res.text, res.prompt_tokens, res.completion_tokens, res.tokens) == ("Hello", 40, 2, 42)
    assert res.content_chunks == 2 and res.finish_reason == "stop" and res.ttft_s == 1.0 and res.usage_seen


@pytest.fixture
def server():
    srv = fake_openai.serve(0)
    fake_openai.STATE.pop("reply_fn", None)
    fake_openai.STATE["token_sleep_s"] = 0.002
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


async def _call(url, limit=None, max_tokens=50):
    async with httpx.AsyncClient() as c:
        return await driver.stream_call(c, driver.Pool("strong", url, "m"), [{"role": "user", "content": "a b c d"}], max_tokens, limit)


def test_stream_call_counts_tokens(server):
    res = asyncio.run(_call(server, max_tokens=30))
    assert res.prompt_tokens == 4 and res.completion_tokens == 30 and res.tokens == 34 and not res.cancelled
    assert res.finish_reason == "length"


def test_stream_call_cancels_at_limit(server):
    fake_openai.STATE["aborted"] = 0
    res = asyncio.run(_call(server, limit=14, max_tokens=200))
    assert res.cancelled and res.tokens == 14 and res.completion_tokens == 10
    import time
    time.sleep(0.2)
    assert fake_openai.STATE["aborted"] == 1   # the server saw the disconnect


# ---------------------------------------------------------------- policies and tasks

def test_pool_choice():
    assert driver.Policy("baseline").pool_for([], 10_000) == "strong"
    dg = driver.Policy("downgrade", budget=1000)
    assert dg.pool_for([], 700) == "strong" and dg.pool_for([], 701) == "cheap"
    esc = driver.Policy("escalate", budget=1000)
    assert esc.pool_for([], 0) == "cheap"
    assert esc.pool_for([{"pool": "cheap", "check_ok": False}], 0) == "strong"
    assert esc.pool_for([{"pool": "cheap", "check_ok": False}, {"pool": "strong", "check_ok": False}], 0) == "strong"
    assert driver.Policy("hard_cut", 1).cuts and driver.Policy("escalate", 1).cuts and not driver.Policy("downgrade", 1).cuts


def scripted(replies):
    """reply_fn for the fake server: pick the reply by step (from the prompt text) and count calls."""
    calls = []

    def fn(prompt, max_tokens):
        step = 1 if "List every quantity" in prompt else 2 if "Write one arithmetic" in prompt else 3
        n = sum(1 for s in calls if s == step)
        calls.append(step)
        text = replies[step][min(n, len(replies[step]) - 1)]
        return text.split(" ")[:max_tokens]
    fn.calls = calls
    return fn


TASK = {"id": 2, "question": "Eggs cost 2 each. Ann buys 9 eggs. What does she pay?", "gold": "18"}
GOOD = {1: ['{"quantities": [{"name": "eggs", "value": 9}, {"name": "price", "value": 2}]}'], 2: ["eggs * price"],
        3: ["9 times 2 is 18.\nAnswer: 18"]}


def _run(url, policy, cheap_url=None):
    pools = {"strong": driver.Pool("strong", url, "s"), "cheap": driver.Pool("cheap", cheap_url or url, "c")}

    async def go():
        async with httpx.AsyncClient() as c:
            return await driver.run_task(c, TASK, policy, pools)
    return asyncio.run(go())


def test_task_success_and_token_sum(server):
    fake_openai.STATE["reply_fn"] = scripted(GOOD)
    r = _run(server, driver.Policy("baseline"))
    assert r["success"] and not r["aborted"] and [s["passed"] for s in r["steps"]] == [True, True, True]
    assert r["tokens"] == sum(a["prompt_tokens"] + a["completion_tokens"] for s in r["steps"] for a in s["attempts"])
    assert r["steps"][-1]["tokens_cum"] == r["tokens"]


def test_retry_then_fail(server):
    fake_openai.STATE["reply_fn"] = fn = scripted({1: ["not json"], 2: ["x"], 3: ["x"]})
    r = _run(server, driver.Policy("baseline"))
    assert not r["success"] and r["failed_step"] == 1 and r["steps"][0]["retries"] == 2 and fn.calls == [1, 1, 1]


def test_wrong_answer_is_not_retried(server):
    fake_openai.STATE["reply_fn"] = fn = scripted(GOOD | {3: ["Answer: 17"]})
    r = _run(server, driver.Policy("baseline"))
    assert not r["success"] and r["failed_step"] == 3 and fn.calls == [1, 2, 3]


def test_hard_cut_aborts_at_budget(server):
    fake_openai.STATE["reply_fn"] = scripted(GOOD)
    full = _run(server, driver.Policy("baseline"))["tokens"]
    r = _run(server, driver.Policy("hard_cut", budget=full - 5))
    assert r["aborted"] and not r["success"] and r["tokens"] == full - 5
    assert r["steps"][-1]["attempts"][-1]["cancelled"]


def test_escalate_moves_failed_step_to_strong(server):
    strong = fake_openai.serve(0)
    try:
        # cheap pool (model "c") replies with bad JSON at step 1, strong pool (model "s") answers correctly;
        # both fake servers share one STATE, so route by the model name in the request
        def fn(prompt, max_tokens, _good=scripted(GOOD), _bad=scripted({1: ["oops"], 2: ["eggs * price"], 3: ["Answer: 18"]})):
            return _good(prompt, max_tokens) if fake_openai.STATE.get("_model") == "s" else _bad(prompt, max_tokens)
        fake_openai.STATE["reply_fn"] = fn
        orig = fake_openai.H.do_POST

        def do_post(self):   # remember which pool's model the request named
            import io
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            fake_openai.STATE["_model"] = json.loads(raw).get("model")
            self.rfile = io.BytesIO(raw)
            return orig(self)
        fake_openai.H.do_POST = do_post
        try:
            r = _run(f"http://127.0.0.1:{strong.server_address[1]}", driver.Policy("escalate", budget=100_000), cheap_url=server)
        finally:
            fake_openai.H.do_POST = orig
        assert r["steps"][0]["pools"] == ["cheap", "strong"] and r["steps"][1]["pools"] == ["cheap"]
        assert r["success"]
    finally:
        strong.shutdown()


def test_batch_plan_orders_vary():
    plan = driver.batch_plan(150, 8, list(driver.POLICIES), seed=10)
    assert len(plan) == 19 and all(sorted(o) == sorted(driver.POLICIES) for _, o in plan)
    assert len({o[0] for _, o in plan}) == 4   # every policy runs first in some batch


def test_p75_and_taskset():
    assert driver.p75([1, 2, 3, 4]) == 3 and driver.p75([5]) == 5
    tasks = driver.load_tasks()
    assert len(tasks) == 150 and len({t["id"] for t in tasks}) == 150
    assert all(float(t["gold"]) == float(t["answer"].split("####")[-1].replace(",", "")) for t in tasks)
