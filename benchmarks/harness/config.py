"""Load the YAML config, layer defaults/experiment/overrides, expand sweeps."""

from __future__ import annotations

import copy
import itertools
from pathlib import Path
from typing import Any

import yaml


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def set_dotted(cfg: dict, dotted: str, value: Any) -> None:
    node = cfg
    *parents, leaf = dotted.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value


def get_dotted(cfg: dict, dotted: str) -> Any:
    node = cfg
    for part in dotted.split("."):
        node = node[part]
    return node


def parse_override(expr: str) -> tuple[str, Any]:
    """`client.requests=5` -> ("client.requests", 5); value parsed as YAML."""
    key, sep, raw = expr.partition("=")
    if not sep:
        raise ValueError(f"--set expects key=value, got {expr!r}")
    return key.strip(), yaml.safe_load(raw)


def load(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def resolve(doc: dict, experiment: str, overrides: list[str] | None = None) -> tuple[dict, dict]:
    """Return (base config for the experiment, sweep dict)."""
    experiments = doc.get("experiments", {})
    if experiment not in experiments:
        raise SystemExit(f"unknown experiment {experiment!r}; choose from: {', '.join(experiments)}")
    exp = copy.deepcopy(experiments[experiment])
    sweep = exp.pop("sweep", {}) or {}
    cfg = deep_merge(doc.get("defaults", {}), exp)
    cfg["experiment"] = experiment
    cfg.setdefault("kind", "server_load")
    for expr in overrides or []:
        key, value = parse_override(expr)
        if key in sweep:
            sweep.pop(key)  # a --set pins a swept key to a single value
        set_dotted(cfg, key, value)
    return cfg, sweep


def expand(cfg: dict, sweep: dict) -> list[tuple[dict, dict]]:
    """Cartesian product of sweep values -> [(point_params, point_config)]."""
    if not sweep:
        return [({}, copy.deepcopy(cfg))]
    keys = list(sweep)
    points = []
    for values in itertools.product(*(sweep[k] for k in keys)):
        params = dict(zip(keys, values))
        point_cfg = copy.deepcopy(cfg)
        for k, v in params.items():
            set_dotted(point_cfg, k, v)
        points.append((params, point_cfg))
    return points


def point_name(params: dict) -> str:
    if not params:
        return "default"
    return "_".join(f"{k.split('.')[-1]}-{v}" for k, v in params.items())
