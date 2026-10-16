"""Regenerate the CALCULATED tables in fabric/design/tables/ and in fabric/DESIGN.md.

DESIGN.md holds each table between `<!-- design-table:NAME -->` and
`<!-- /design-table -->`; this rewrites what is between the markers.

    python -m fabric.design.tables [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from fabric.design import collectives, sizing

HERE = Path(__file__).parent
DESIGN = HERE.parent / "DESIGN.md"
OUT = HERE / "tables"


def render(cfg: dict) -> dict[str, str]:
    counts = cfg["sizing"]["gpu_counts"]
    return {
        "training": collectives.training_md(cfg),
        "slow-link": collectives.slow_link_md(cfg),
        "inference": collectives.inference_md(cfg),
        "backend": sizing.backend_md(cfg, counts),
        "ceiling": sizing.ceiling_md(cfg),
        "other-networks": sizing.other_networks_md(cfg, counts),
    }


def fill(doc: str, tables: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        return f"{m.group(1)}\n{tables[m.group(2)]}\n{m.group(3)}"
    return re.sub(r"(<!-- design-table:([a-z-]+) -->)\n.*?\n?(<!-- /design-table -->)", sub, doc,
                  flags=re.S)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=collectives.DEFAULT_CONFIG)
    p.add_argument("--check", action="store_true", help="fail if DESIGN.md is stale")
    a = p.parse_args(argv)
    tables = render(yaml.safe_load(a.config.read_text()))
    doc = DESIGN.read_text()
    new = fill(doc, tables)
    if a.check:
        if new != doc:
            print("fabric/DESIGN.md tables are stale: run `make design-tables`", file=sys.stderr)
            return 1
        return 0
    OUT.mkdir(exist_ok=True)
    (OUT / "collectives.md").write_text(
        "\n\n".join(tables[k] for k in ("training", "slow-link", "inference")) + "\n")
    (OUT / "sizing.md").write_text(
        "\n\n".join(tables[k] for k in ("backend", "ceiling", "other-networks")) + "\n")
    DESIGN.write_text(new)
    print(f"wrote {OUT}/*.md and {DESIGN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
