"""Per-step checkers for the 3-step GSM8K task. Each returns Check(ok, reason, value).

    step 1  check_quantities(text)          valid JSON, schema {"quantities": [{"name": <identifier>, "value": <number>}, ...]}
    step 2  check_expression(text, qs)      one arithmetic expression over those names, evaluated by evaluator.safe_eval
    step 3  check_answer_format(text)       a number on an 'Answer: <number>' line   (retry trigger)
            final_success(value, gold)      that number equals the GSM8K answer       (task success, never a retry trigger)

Step 3's retry check is the format only: retrying on the gold comparison would hand the policy the answer key, which a
production checker never has (results/t4/task_budget.md, "Decisions made").
"""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import dataclass

from benchmarks.task_budget.evaluator import EvalError, safe_eval

FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
ANSWER = re.compile(r"Answer:\s*\**\s*\$?\s*(-?[\d,]*\.?\d+)", re.I)


@dataclass
class Check:
    ok: bool
    reason: str = ""
    value: object = None


def strip_fences(text: str) -> str:
    return FENCE.sub("", text.strip()).strip()


def check_quantities(text: str) -> Check:
    try:
        obj = json.loads(strip_fences(text))
    except json.JSONDecodeError as exc:
        return Check(False, f"not valid JSON ({exc.msg})")
    if not isinstance(obj, dict) or set(obj) != {"quantities"}:
        return Check(False, 'top level must be an object with exactly the key "quantities"')
    qs = obj["quantities"]
    if not isinstance(qs, list) or not qs:
        return Check(False, '"quantities" must be a non-empty list')
    out: dict[str, float] = {}
    for q in qs:
        if not isinstance(q, dict) or set(q) != {"name", "value"}:
            return Check(False, 'each quantity must be an object with exactly "name" and "value"')
        name, value = q["name"], q["value"]
        if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name):
            return Check(False, f"name {name!r} is not an identifier")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return Check(False, f"value of {name!r} is not a number")
        if name in out:
            return Check(False, f"duplicate name {name!r}")
        out[name] = float(value)
    return Check(True, "", out)


def extract_expression(text: str) -> str:
    """The expression line: last non-empty line, without fences, an 'Expression:' label, a leading 'x =' or a final '.'."""
    lines = [l.strip() for l in strip_fences(text).splitlines() if l.strip()]
    if not lines:
        return ""
    expr = re.sub(r"^(expression|answer)\s*:\s*", "", lines[-1], flags=re.I).strip("`").strip()
    m = re.match(r"^[A-Za-z_]\w*\s*=(?!=)\s*(.+)$", expr)
    if m:
        expr = m.group(1)
    return expr.rstrip(".").strip()


def check_expression(text: str, quantities: dict[str, float]) -> Check:
    expr = extract_expression(text)
    if not expr:
        return Check(False, "no expression found")
    try:
        return Check(True, "", safe_eval(expr, quantities))
    except EvalError as exc:
        return Check(False, f"expression {expr[:80]!r} rejected: {exc}")


def check_answer_format(text: str) -> Check:
    found = ANSWER.findall(text)
    if not found:
        return Check(False, "no line 'Answer: <number>'")
    try:
        return Check(True, "", float(found[-1].replace(",", "")))
    except ValueError:
        return Check(False, f"answer {found[-1]!r} is not a number")


def final_success(value: float | None, gold: str) -> bool:
    return value is not None and abs(value - float(gold)) < 1e-6
