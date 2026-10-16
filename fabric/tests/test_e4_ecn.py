from fabric.experiments.e4_ecn import scaled_red_parameters


def test_red_thresholds_scale_from_intent_rate() -> None:
    intent = {
        "qos": {
            "target": {"port_speed_gbps": 400},
            "ecn": {
                "kmin_bytes": 150_000,
                "kmax_bytes": 1_500_000,
                "pmax_percent": 100,
            },
        },
    }

    scaled = scaled_red_parameters(intent, 1000)

    assert scaled == {
        "hardware_rate_mbit": 400_000,
        "emulated_rate_mbit": 1000,
        "scale": 0.0025,
        "unclamped_min_bytes": 375,
        "minimum_packet_floor_bytes": 1500,
        "min_bytes": 1500,
        "max_bytes": 3750,
        "max_probability": 1.0,
        "avpkt_bytes": 1500,
        "burst_packets": 1,
        "limit_bytes": 15000,
    }


def test_red_thresholds_preserve_intent_at_target_rate() -> None:
    intent = {
        "qos": {
            "target": {"port_speed_gbps": 400},
            "ecn": {
                "kmin_bytes": 150_000,
                "kmax_bytes": 1_500_000,
                "pmax_percent": 100,
            },
        },
    }

    scaled = scaled_red_parameters(intent, 400_000)

    assert scaled["unclamped_min_bytes"] == 150_000
    assert scaled["min_bytes"] == 150_000
    assert scaled["max_bytes"] == 1_500_000


def test_red_thresholds_keep_xoff_above_packet_floored_kmax_at_500_mbit() -> None:
    intent = {
        "qos": {
            "target": {"port_speed_gbps": 400},
            "ecn": {
                "kmin_bytes": 150_000,
                "kmax_bytes": 1_500_000,
                "pmax_percent": 100,
            },
            "pfc": {"xoff_threshold_bytes": 3_000_000},
        },
    }

    scaled = scaled_red_parameters(intent, 500)
    xoff = round(intent["qos"]["pfc"]["xoff_threshold_bytes"] * scaled["scale"])

    assert scaled["unclamped_min_bytes"] == 188
    assert scaled["min_bytes"] == 1500
    assert scaled["max_bytes"] == 3000
    assert scaled["max_bytes"] < xoff == 3750


def test_red_rate_must_be_positive() -> None:
    import pytest

    with pytest.raises(ValueError, match="must be positive"):
        scaled_red_parameters({}, 0)
