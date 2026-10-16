from __future__ import annotations

from collections import Counter

import pytest
import yaml

from fabric.intent.schema.validate import INTENT_PATH, load_intent, validate_semantics
from fabric.render.shaping import fabric_ports, pin_assignment, pin_scripts, shape_scripts


def raw_intent() -> dict:
    with INTENT_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_shape_scripts_cover_both_ends_of_every_fabric_link() -> None:
    intent = load_intent()
    scripts = shape_scripts(intent)
    fabric_links = [link for link in intent["links"] if link["kind"] == "fabric"]
    expected = {
        (endpoint["node"], endpoint["interface"])
        for link in fabric_links
        for endpoint in (link["a"], link["b"])
    }
    rendered = {
        (node, line.split()[4])
        for node, pair in scripts.items()
        for line in pair["on"].splitlines()
        if line.startswith("tc qdisc replace")
    }
    assert rendered == expected
    rate = intent["lab_shaping"]["uplink_rate_mbit"]
    assert all(f"tbf rate {rate}mbit" in pair["on"] for pair in scripts.values())
    assert all("tc qdisc del" in pair["off"] for pair in scripts.values())


@pytest.mark.parametrize("pattern,per_uplink", [("ring", 1), ("all-to-all", 2)])
def test_pins_split_cross_leaf_pairs_evenly_over_uplinks(pattern: str, per_uplink: int) -> None:
    intent = load_intent()
    assignment = pin_assignment(intent, pattern)
    ports = fabric_ports(intent)
    assert set(assignment) == {"leaf1", "leaf2"}  # rail-A hosts live on leaf1/leaf2
    for leaf, pins in assignment.items():
        counts = Counter(pin["uplink"] for pin in pins if pin["pattern_pair"])
        assert counts == {port: per_uplink for port in ports[leaf]}
        assert all(pin["source"] != pin["destination"] for pin in pins)
    spine_index = {
        (pin["source"], pin["destination"]): ports[leaf].index(pin["uplink"])
        for leaf, pins in assignment.items() for pin in pins
    }
    assert all(spine_index[(d, s)] == index for (s, d), index in spine_index.items())


def test_pin_scripts_use_unnumbered_onlink_next_hop_and_clean_up() -> None:
    scripts = pin_scripts(load_intent(), "ring")
    assert "via 169.254.0.1 dev eth1 onlink table 201" in scripts["leaf1"]["on"]
    assert "from 10.210.0.2 to 10.210.0.10 table" in scripts["leaf1"]["on"]
    assert "ip route flush table 201" in scripts["leaf1"]["off"]
    assert "ip rule add" not in scripts["leaf3"]["on"]


def test_rejects_shaping_pin_rail_not_declared() -> None:
    intent = raw_intent()
    intent["lab_shaping"]["pin_rail"] = "C"
    with pytest.raises(ValueError, match="pin_rail C is not a declared rail"):
        validate_semantics(intent)
