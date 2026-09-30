"""llama-bench wrapper for the memory-bandwidth experiment (no server involved)."""

from __future__ import annotations

import json
import os
import subprocess
import time


def run_llama_bench(cfg: dict) -> list[dict]:
    b, s = cfg["bench"], cfg["server"]
    args = [
        os.path.expanduser(b["binary"]), "-m", os.path.expanduser(s["model_path"]),
        "-p", str(b["n_prompt"]), "-n", str(b["n_gen"]), "-t", str(s["threads"]),
        "-r", str(b["repetitions"]), "-o", "jsonl",
    ]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


def summarize_bench(rows: list[dict]) -> dict:
    """Decode reads (roughly) every weight once per token: GB/s ~= tok/s x model bytes."""
    gen = [r for r in rows if r.get("n_gen", 0) > 0 and r.get("n_prompt", 0) == 0]
    if not gen:
        return {}
    r = gen[0]
    return {
        "gen_tok_s": round(r["avg_ts"], 2),
        "gen_tok_s_stddev": round(r["stddev_ts"], 2),
        "model_bytes": r["model_size"],
        "effective_bw_gb_s": round(r["avg_ts"] * r["model_size"] / 1e9, 2),
        "backend": r.get("backends") or r.get("backend"),
    }


def memcopy_gb_s(size_mib: int = 1024, repeats: int = 5) -> float:
    """Single-threaded memcpy reference (read + write counted), best of N.

    A lower bound on what one core can pull; the multi-thread decode number
    should be compared against this and the DIMM spec (DDR4-2933 dual channel ~ 47 GB/s).
    """
    src = bytearray(size_mib * 1024 * 1024)
    dst = bytearray(len(src))
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        dst[:] = src
        best = min(best, time.perf_counter() - t0)
    return round(2 * len(src) / best / 1e9, 2)
