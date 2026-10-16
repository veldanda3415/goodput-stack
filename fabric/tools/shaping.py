"""Apply the rendered EMULATED lab shaping profile and even-split pins.

The scripts come from `make fabric-render` (fabric/build/shaping/); this tool
only runs them in the router containers, so intent stays the source of truth.

  python -m fabric.tools.shaping on|off|status
  python -m fabric.tools.shaping pin ring|all-to-all
  python -m fabric.tools.shaping unpin
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from fabric.intent.schema.validate import load_intent
from fabric.render.shaping import PIN_RULE_PRIORITY, fabric_ports
from fabric.tests.lab import node_json, node_result, require_lab

BUILD = Path(__file__).resolve().parents[2] / "fabric" / "build" / "shaping"


def run_script(node: str, path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"missing rendered script {path}; run make fabric-render")
    encoded = base64.b64encode(path.read_bytes()).decode()
    node_result(node, f"sh -c 'echo {encoded} | base64 -d | sh'")


def apply_shape(intent: dict[str, Any], enabled: bool) -> None:
    for node in fabric_ports(intent):
        run_script(node, BUILD / f"{node}-shape-{'on' if enabled else 'off'}.sh")


def apply_pins(intent: dict[str, Any], pattern: str | None) -> None:
    """Remove any pins, then install `pattern`'s pins (None = ECMP only)."""
    leaves = [n["name"] for n in intent["nodes"] if n["role"] == "leaf"]
    for leaf in leaves:
        run_script(leaf, BUILD / f"{leaf}-pin-off.sh")
        if pattern:
            run_script(leaf, BUILD / f"{leaf}-pin-{pattern}.sh")


def status(intent: dict[str, Any]) -> dict[str, Any]:
    rate = f"{intent['lab_shaping']['uplink_rate_mbit']}Mbit"
    shaped, total = [], 0
    for node, interfaces in fabric_ports(intent).items():
        qdiscs = {q["dev"]: q for q in node_json(node, "tc -j qdisc show") if q.get("root")}
        for interface in interfaces:
            total += 1
            q = qdiscs.get(interface, {})
            if q.get("kind") == "tbf":
                shaped.append({"port": f"{node}:{interface}", "rate": q.get("options", {}).get("rate")})
    pins = {}
    for leaf in (n["name"] for n in intent["nodes"] if n["role"] == "leaf"):
        rules = node_json(leaf, "ip -j rule show")
        pins[leaf] = [
            r for r in rules
            if PIN_RULE_PRIORITY < int(r.get("priority", 0)) < PIN_RULE_PRIORITY + 1000
        ]
    return {
        "intended_rate": rate,
        "shaped_ports": shaped,
        "fabric_ports": total,
        "fully_shaped": len(shaped) == total,
        "pin_rules": {leaf: len(rules) for leaf, rules in pins.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["on", "off", "status", "pin", "unpin"])
    parser.add_argument("pattern", nargs="?", choices=["ring", "all-to-all"])
    args = parser.parse_args()
    require_lab()
    intent = load_intent()
    if args.command in ("on", "off"):
        apply_shape(intent, args.command == "on")
    elif args.command == "pin":
        if not args.pattern:
            parser.error("pin needs a pattern")
        apply_pins(intent, args.pattern)
    elif args.command == "unpin":
        apply_pins(intent, None)
    print(json.dumps(status(intent), indent=2))


if __name__ == "__main__":
    main()
