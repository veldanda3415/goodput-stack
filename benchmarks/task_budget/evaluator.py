"""Restricted arithmetic evaluator for step 2: never calls eval() on model output.

    safe_eval("price * (1 + rate / 100)", {"price": 80000, "rate": 150})  -> 200000.0

Parses with `ast.parse(mode="eval")` and walks the tree itself. Allowed: int/float literals, names bound in `names`,
+ - * / // % and **, unary + and -, parentheses. Everything else (calls, attributes, subscripts, comparisons,
strings, lambdas, comprehensions, ...) raises EvalError. Limits: expression length, tree size, exponent size and
result magnitude, so a hostile string cannot hang the driver or exhaust memory.
"""

from __future__ import annotations

import ast
import math
import operator

MAX_LEN = 500
MAX_NODES = 200
MAX_EXPONENT = 64
MAX_ABS = 1e15

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class EvalError(ValueError):
    pass


def safe_eval(expr: str, names: dict[str, float] | None = None) -> float:
    names = names or {}
    if len(expr) > MAX_LEN:
        raise EvalError(f"expression longer than {MAX_LEN} characters")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise EvalError(f"syntax error: {exc.msg}") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise EvalError(f"expression has more than {MAX_NODES} nodes")
    value = _eval(tree.body, names)
    if not math.isfinite(value):
        raise EvalError("result is not finite")
    return float(value)


def _check(x: float) -> float:
    if isinstance(x, complex) or not math.isfinite(x) or abs(x) > MAX_ABS:
        raise EvalError("value out of range")
    return x


def _eval(node: ast.AST, names: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise EvalError(f"literal {node.value!r} is not a number")
        return _check(node.value)
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise EvalError(f"unknown name {node.id!r}")
        return _check(float(names[node.id]))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check(_UNARY[type(node.op)](_eval(node.operand, names)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left, names), _eval(node.right, names)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise EvalError(f"exponent above {MAX_EXPONENT}")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise EvalError("division by zero")
        return _check(_BIN[type(node.op)](left, right))
    raise EvalError(f"{type(node).__name__} is not allowed")
