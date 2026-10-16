from fabric.tools.collective_gen import (
    collective_pairs,
    parse_iperf_streams,
    summarize_uplinks,
)


def inventory() -> dict[str, dict[str, str]]:
    return {
        "host1": {"leaf": "leaf1"},
        "host2": {"leaf": "leaf1"},
        "host3": {"leaf": "leaf2"},
        "host4": {"leaf": "leaf2"},
    }


def test_ring_pairs_alternate_leaves_and_close_cycle() -> None:
    hosts = inventory()
    pairs = collective_pairs(hosts, "ring")

    assert pairs == [
        ("host1", "host3"),
        ("host3", "host2"),
        ("host2", "host4"),
        ("host4", "host1"),
    ]
    assert all(
        hosts[source]["leaf"] != hosts[destination]["leaf"]
        for source, destination in pairs
    )


def test_all_to_all_contains_every_ordered_distinct_pair() -> None:
    pairs = collective_pairs(inventory(), "all-to-all")

    assert len(pairs) == 12
    assert len(set(pairs)) == 12
    assert all(source != destination for source, destination in pairs)


def test_parse_iperf_records_each_stream_and_checks_requested_bytes() -> None:
    document = {
        "intervals": [
            {
                "streams": [
                    {"socket": 41000, "start": 0, "end": 1, "bytes": 2048},
                    {"socket": 41001, "start": 0, "end": 1, "bytes": 4096},
                ]
            },
            {
                "streams": [
                    {"socket": 41000, "start": 1, "end": 2, "bytes": 4096},
                    {"socket": 41001, "start": 1, "end": 2, "bytes": 4096},
                ]
            },
        ],
        "end": {
            "streams": [
                {
                    "sender": {"socket": 41000, "bytes": 6144},
                    "receiver": {
                        "socket": 41000,
                        "bytes": 4096,
                        "bits_per_second": 100_000_000,
                        "seconds": 2,
                    },
                },
                {
                    "sender": {"socket": 41001, "bytes": 8192},
                    "receiver": {
                        "socket": 41001,
                        "bytes": 4096,
                        "bits_per_second": 200_000_000,
                        "seconds": 2,
                    },
                },
            ]
        }
    }

    flows = parse_iperf_streams(document, 4096)

    assert [flow["sender_socket"] for flow in flows] == [41000, 41001]
    assert [flow["throughput_gbps"] for flow in flows] == [0.1, 0.2]
    assert [flow["time_to_target_bytes_seconds"] for flow in flows] == [1.5, 1.0]


def test_summarize_uplinks_counts_idle_ecmp_member_in_imbalance() -> None:
    summary = summarize_uplinks({
        "leaf1": {"eth1": 100, "eth2": 0},
        "leaf2": {"eth1": 40, "eth2": 60},
        "leaf3": {"eth1": 0, "eth2": 0},
    })

    assert summary["per_leaf"]["leaf1"]["max_mean_imbalance"] == 2.0
    assert summary["per_leaf"]["leaf2"]["max_mean_imbalance"] == 1.2
    assert summary["per_leaf"]["leaf3"]["max_mean_imbalance"] is None
    assert summary["worst_active_leaf_imbalance"] == 2.0
