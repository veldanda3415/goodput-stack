from __future__ import annotations

import json
import subprocess
from typing import Any

from fabric.intent.schema.validate import load_intent


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
