"""Unit tests for benchmarks/gpu_sampler.py parsing (local, no GPU).

    .venv/bin/python -m pytest benchmarks/tests -q
"""

from __future__ import annotations

import csv

from benchmarks import gpu_sampler as gs

# Shape of `nvidia-smi --help-query-gpu` (driver 5xx): a quoted property line (with aliases), then description lines,
# some of which also start with a quote.
HELP = '''List of valid properties to query for the switch "--query-gpu=":

Section about timestamp properties
"timestamp"
The timestamp of when the query was made in format "YYYY/MM/DD HH:MM:SS.msec".

"pstate"
The current performance state for the GPU. States range from P0 (maximum performance) to P12 (minimum performance).

"clocks_event_reasons.supported" or "clocks_throttle_reasons.supported"
Bitmask of supported clock event reasons. See nvml.h for more details.

"clocks_event_reasons.active" or "clocks_throttle_reasons.active"
Bitmask of active clock event reasons. See nvml.h for more details.

"clocks_event_reasons.gpu_idle" or "clocks_throttle_reasons.gpu_idle"
Nothing is running on the GPU and the clocks are dropping to Idle state.

"clocks_event_reasons.applications_clocks_setting" or "clocks_throttle_reasons.applications_clocks_setting"
GPU clocks are limited by applications clocks setting.

"clocks_event_reasons.sw_power_cap" or "clocks_throttle_reasons.sw_power_cap"
SW Power Scaling algorithm is reducing the clocks below requested clocks.

"clocks_event_reasons.hw_slowdown" or "clocks_throttle_reasons.hw_slowdown"
HW Slowdown is engaged.

"clocks_event_reasons.hw_thermal_slowdown" or "clocks_throttle_reasons.hw_thermal_slowdown"
HW Thermal Slowdown.

"clocks_event_reasons.hw_power_brake_slowdown" or "clocks_throttle_reasons.hw_power_brake_slowdown"
HW Power Brake Slowdown.

"clocks_event_reasons.sw_thermal_slowdown" or "clocks_throttle_reasons.sw_thermal_slowdown"
SW Thermal capping algorithm is reducing clocks below requested clocks.

"clocks_event_reasons.sync_boost" or "clocks_throttle_reasons.sync_boost"
Sync Boost.

"power.draw"
The last measured power draw for the entire board, in watts.

"power.draw.instant"
The last measured power draw for the entire board, in watts.

"power.limit"
"enforced.power.limit"
"power.default_limit"
"power.min_limit"
"power.max_limit"
"temperature.gpu"
"clocks.current.sm" or "clocks.sm"
"clocks.current.memory" or "clocks.mem"
"clocks.max.sm" or "clocks.max.sm"
"clocks.applications.graphics" or "clocks.applications.gr"
"Display Clock Setting" is a description line, not a property.
'''


def test_parse_help_groups_and_aliases():
    groups = gs.parse_help_query_gpu(HELP)
    assert ["timestamp"] in groups
    assert ["clocks_event_reasons.active", "clocks_throttle_reasons.active"] in groups
    assert ["clocks.current.sm", "clocks.sm"] in groups
    assert not any("Display" in n for g in groups for n in g)


def test_select_fields_prefers_throttle_names_and_reports_missing():
    sel = gs.select_fields(gs.parse_help_query_gpu(HELP))
    f = sel["fields"]
    for w in ("clocks.sm", "clocks.mem", "clocks.max.sm", "clocks.applications.graphics", "power.draw", "power.draw.instant",
              "power.limit", "enforced.power.limit", "power.default_limit", "power.min_limit", "power.max_limit",
              "temperature.gpu", "pstate"):
        assert w in f, w
    reasons = [x for x in f if x.startswith("clocks_")]
    assert all(x.startswith("clocks_throttle_reasons.") for x in reasons)
    assert {"clocks_throttle_reasons.sw_power_cap", "clocks_throttle_reasons.sync_boost",
            "clocks_throttle_reasons.active", "clocks_throttle_reasons.supported"} <= set(reasons)
    assert len(reasons) == len(set(reasons)) == 10
    assert sel["aliases"]["clocks.sm"] == ["clocks.current.sm"]
    assert sel["missing"] == []          # power.draw.average is optional


def test_select_fields_event_only_driver_and_missing():
    groups = [["clocks_event_reasons.sw_power_cap"], ["clocks.sm"]]
    sel = gs.select_fields(groups)
    assert "clocks_event_reasons.sw_power_cap" in sel["fields"]
    assert "power.limit" in sel["missing"]
    assert "clocks_throttle_reasons.hw_slowdown" in sel["missing"]
    assert "clocks_throttle_reasons.sw_power_cap" not in sel["missing"]   # present under its event name


def test_parse_values():
    assert gs.parse_value("x", " Active") == 1
    assert gs.parse_value("x", "Not Active") == 0
    assert gs.parse_value("x", "[N/A]") == ""
    assert gs.parse_value("x", "[Not Supported]") == ""
    assert gs.parse_value("x", "0x0000000000000004") == "0x0000000000000004"
    assert gs.parse_value("x", "65.43") == 65.43
    assert gs.parse_value("x", "1590") == 1590
    assert gs.parse_value("x", "P0") == "P0"


def test_parse_smi_line_and_length_mismatch():
    fields = ["clocks.sm", "power.draw", "pstate", "clocks_throttle_reasons.sw_power_cap"]
    row = gs.parse_smi_line(fields, "990, 66.12, P0, Active\n")
    assert row == {"clocks.sm": 990, "power.draw": 66.12, "pstate": "P0", "clocks_throttle_reasons.sw_power_cap": 1}
    assert "smi_error" in gs.parse_smi_line(fields, "990, 66.12\n")


def test_summarize_rows_reason_fractions(tmp_path):
    rows = [{"t_unix": str(i), "sm_clock_mhz": str(c), "clocks.sm": str(c), "power.draw": "66.0", "pstate": "P0",
             "clocks_throttle_reasons.sw_power_cap": str(cap), "clocks_throttle_reasons.hw_slowdown": "0",
             "clocks_throttle_reasons.active": "0x4" if cap else "0x0", "error": ""}
            for i, (c, cap) in enumerate([(1000, 1), (1000, 1), (1590, 0), (990, 1)])]
    s = gs.summarize_rows(rows)
    assert s["gpu_samples"] == 4
    assert s["gpu_clocks_sm_mean"] == 1145.0
    assert s["gpu_reason_sw_power_cap_frac"] == 0.75
    assert s["gpu_reason_hw_slowdown_frac"] == 0.0
    assert "gpu_reason_active_frac" not in s   # bitmask, not a flag
    assert s["gpu_reason_active_masks"] == {"0x0": 1, "0x4": 3}
    assert s["gpu_pstate_counts"] == {"P0": 4}
    # file + window
    p = tmp_path / "g.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert gs.summarize(p, 1, 2)["gpu_samples"] == 2
