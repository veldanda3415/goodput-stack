"""Build the fixed 150-problem GSM8K task set (run once, output committed).

    python -m benchmarks.task_budget.make_taskset ROWS_DIR [--seed 0] [--n 150]

ROWS_DIR holds the JSON pages of the HF datasets-server rows API for openai/gsm8k, config main, split test
(`https://datasets-server.huggingface.co/rows?dataset=openai%2Fgsm8k&config=main&split=test&offset=K&length=100`,
K = 0, 100, ..., 1300). The task ID is the row index in the test split. Selection: random.Random(seed).sample over all
indices, then sorted. Gold answer: the number after '#### ' in the GSM8K answer, commas removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

OUT = Path(__file__).with_name("gsm8k_test_150.jsonl")


def gold(answer: str) -> str:
    return answer.split("####")[-1].strip().replace(",", "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows_dir", type=Path)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    rows = {}
    for f in sorted(a.rows_dir.glob("rows_*.json")):
        for r in json.loads(f.read_text())["rows"]:
            rows[r["row_idx"]] = r["row"]
    assert len(rows) == 1319, len(rows)
    ids = sorted(random.Random(a.seed).sample(sorted(rows), a.n))
    lines = [json.dumps({"id": i, "question": rows[i]["question"], "answer": rows[i]["answer"], "gold": gold(rows[i]["answer"])})
             for i in ids]
    OUT.write_text("\n".join(lines) + "\n")
    print(f"{len(ids)} tasks -> {OUT.name}, sha256 {hashlib.sha256(OUT.read_bytes()).hexdigest()}")
    print("ids:", ids)


if __name__ == "__main__":
    main()
