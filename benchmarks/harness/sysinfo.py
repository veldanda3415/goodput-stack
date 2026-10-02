"""Provenance captured once per run: hardware, OS, engine build, model file."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], cwd: str | None = None) -> str | None:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=20).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def mem_available_mib() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return 0


def sha256_head(path: Path, limit: int = 64 * 1024 * 1024) -> str:
    """Hash of the first 64 MiB + file size: identifies the model file without reading GBs."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(limit))
    h.update(str(path.stat().st_size).encode())
    return h.hexdigest()


def host() -> dict:
    """The machine the client (and, for local targets, the server) runs on."""
    cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                if l.startswith("model name")), platform.processor())
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": platform.node(),
        "kernel": platform.release(),
        "wsl2": "microsoft" in platform.release().lower(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "mem_total_mib": int(next(l for l in Path("/proc/meminfo").read_text().splitlines()
                                  if l.startswith("MemTotal:")).split()[1]) // 1024,
        "mem_available_mib": mem_available_mib(),
        "python": platform.python_version(),
        "repo_commit": _run(["git", "rev-parse", "--short", "HEAD"]),
    }


def collect(cfg: dict) -> dict:
    """Host + local llama.cpp build + model file. In-cluster targets: engine/k8s.py collect()."""
    s = cfg["server"]
    binary = Path(os.path.expanduser(s["binary"]))
    llama_repo = binary.parents[2] if len(binary.parents) > 2 else binary.parent
    commit = _run(["git", "rev-parse", "--short", "HEAD"], cwd=str(llama_repo))
    info = host() | {
        "engine": f"llama.cpp {commit}",
        "llama_cpp_commit": commit,
        "llama_cpp_dirty": bool(_run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=str(llama_repo))),
        "llama_server_version": _run([str(binary), "--version"]),
        "measurement": "real (CPU, local)",
    }
    if s.get("model_path"):
        model = Path(os.path.expanduser(s["model_path"]))
        info |= {"model_file": model.name, "model_bytes": model.stat().st_size, "model_sha256_head64m": sha256_head(model)}
    else:
        info["model_hf_repo"] = s["hf_repo"]
    return info
