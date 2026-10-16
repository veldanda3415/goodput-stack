from __future__ import annotations

import json
import subprocess
from typing import Any

from fabric.intent.schema.validate import load_intent


def lab_nodes(name: str | None = None) -> dict[str, str]:
    """Running lab containers as {node: state}; {} when the lab is not deployed."""
    name = name or load_intent()["name"]
    completed = subprocess.run(
        ["containerlab", "inspect", "--runtime", "podman", "--name", name, "--format", "json", "--log-level", "error"],
        check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        return {}
    containers = [c for group in json.loads(completed.stdout).values() for c in group]
    prefix = f"clab-{name}-"
    return {c["name"].removeprefix(prefix): c.get("state", "?") for c in containers}


def require_lab() -> None:
    """Exit with a one-line hint instead of a containerlab traceback when the lab is down."""
    name = load_intent()["name"]
    if not lab_nodes(name):
        raise SystemExit(f"fabric lab '{name}' is not running: run `make fabric-up` (then `make fabric-shape-on` "
                         "for shaped experiments). `make fabric-status` shows what is up.")


def node_result(node: str, command: str) -> dict[str, Any]:
    intent = load_intent()
    completed = subprocess.run(
        [
            "containerlab", "exec", "--runtime", "podman",
            "--name", intent["name"],
            "--label", f"clab-node-name={node}",
            "--format", "json", "--log-level", "error",
            "--cmd", command,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"containerlab exec failed on {node}: {command}\n"
            f"exit={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    container = f"clab-{intent['name']}-{node}"
    result = json.loads(completed.stdout)[container][0]
    if result["return-code"] != 0:
        raise AssertionError(
            f"command failed on {node}: {command}\n"
            f"exit={result['return-code']}\nstdout={result['stdout']}\nstderr={result['stderr']}"
        )
    return result


def node_json(node: str, command: str) -> Any:
    output = node_result(node, command)["stdout"]
    if not isinstance(output, (dict, list)):
        raise AssertionError(f"expected JSON stdout from {node}: {command}; got {output!r}")
    return output
