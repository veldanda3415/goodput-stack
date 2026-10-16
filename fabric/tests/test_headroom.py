from __future__ import annotations

import pytest

from fabric.tools.headroom import cable_bytes_round_trip, headroom, ieee_response_bytes, switch_total


def test_matches_h3c_worked_example_100g_100m() -> None:
    # H3C S6805/S9820 RDMA Technical Reference: 100GE, 100 m,
    # 9216 + 1536 + 3840 + 13000 = 27592 bytes.
    result = headroom(100, 100, mtu_s=1536)
    assert result.link_delay_2x == 13000
    assert result.total == 27592


def test_hand_computed_400g_10m() -> None:
    # 2 * 10 m * 5.2 ns/m = 104 ns; 104e-9 s * 400e9 b/s / 8 = 5200 bytes.
    # 9216 + 4200 + 3840 + 5200 = 22456 bytes.
    assert cable_bytes_round_trip(400, 10) == 5200
    assert headroom(400, 10, mtu_s=4200).total == 22456


def test_switch_total_scales_with_ports_and_classes() -> None:
    assert switch_total(22456, 64, 2) == 22456 * 128


def test_rejects_nonsense_inputs() -> None:
    with pytest.raises(ValueError):
        headroom(0, 10, mtu_s=4200)


def test_ieee_response_is_pause_quanta_times_64_bytes() -> None:
    assert ieee_response_bytes(400) == 905 * 64
    assert ieee_response_bytes(800) is None
