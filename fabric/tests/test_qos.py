from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from fabric.intent.schema.validate import INTENT_PATH, SCHEMA_PATH, load_intent, validate_semantics
from fabric.render.render import render

GOLDEN = Path(__file__).with_name("golden")


def raw_intent() -> dict:
    with INTENT_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def classes(intent: dict) -> dict[str, dict]:
    return {cls["role"]: cls for cls in intent["qos"]["classes"]}


def test_rejects_ecn_threshold_at_or_above_pfc_xoff() -> None:
    intent = raw_intent()
    intent["qos"]["ecn"]["kmax_bytes"] = intent["qos"]["pfc"]["xoff_threshold_bytes"]
    with pytest.raises(ValueError, match="ECN Kmax must be below the PFC XOFF threshold"):
        validate_semantics(intent)


def test_rejects_missing_cnp_class() -> None:
    intent = raw_intent()
    intent["qos"]["classes"] = [cls for cls in intent["qos"]["classes"] if cls["role"] != "cnp"]
    with pytest.raises(ValueError, match="exactly one cnp class"):
        validate_semantics(intent)


def test_rejects_lossless_class_without_pfc() -> None:
    intent = raw_intent()
    intent["qos"]["pfc"]["priorities"] = []
    with pytest.raises(ValueError, match="lossless class roce has no PFC priority"):
        validate_semantics(intent)


def test_rejects_lossless_class_missing_pfc_priority() -> None:
    intent = raw_intent()
    del classes(intent)["roce"]["pfc_priority"]
    with pytest.raises(ValueError, match="no PFC priority"):
        validate_semantics(intent)


def test_schema_rejects_watchdog_outside_sonic_yang_range() -> None:
    intent = raw_intent()
    intent["qos"]["pfc_watchdog"]["detection_ms"] = 50
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(intent)


def test_rejects_duplicate_dscp_mapping() -> None:
    intent = raw_intent()
    classes(intent)["cnp"]["dscp"] = copy.deepcopy(classes(intent)["roce"]["dscp"])
    with pytest.raises(ValueError, match="DSCP value is mapped to more than one"):
        validate_semantics(intent)


def test_leaf1_sonic_render_matches_golden(tmp_path: Path) -> None:
    render(load_intent(), tmp_path)
    rendered = json.loads((tmp_path / "sonic/leaf1/config_db.qos.json").read_text(encoding="utf-8"))
    golden = json.loads((GOLDEN / "leaf1.config_db.qos.json").read_text(encoding="utf-8"))
    assert rendered == golden
    assert rendered["DSCP_TO_TC_MAP"]["ROCE"]["26"] == "3"
    assert rendered["DSCP_TO_TC_MAP"]["ROCE"]["48"] == "6"
    assert rendered["PORT_QOS_MAP"]["Ethernet0"]["pfc_enable"] == "3"


def test_host1_linux_qos_render_matches_golden(tmp_path: Path) -> None:
    render(load_intent(), tmp_path)
    assert (tmp_path / "hosts/host1-qos.sh").read_text(encoding="utf-8") == (
        GOLDEN / "host1-qos.sh"
    ).read_text(encoding="utf-8")
