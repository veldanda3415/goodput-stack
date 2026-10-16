from fabric.telemetry.exporter import (
    host_tcp_counters,
    metric_line,
    qdisc_counters,
    root_qdisc_drops,
    state_records,
)


def test_metric_line_escapes_prometheus_label_values() -> None:
    assert metric_line(
        "fabric_test", 3, node='leaf"1', interface="eth\\1\n"
    ) == 'fabric_test{interface="eth\\\\1\\n",node="leaf\\"1"} 3'


def test_qdisc_counters_aggregate_red_and_ecn_statistics() -> None:
    assert qdisc_counters([
        {"xstats": {"marked": 2, "early": 3, "pdrop": 4}},
        {"options": {"xstats": {"prob_mark": 5, "forced_mark": 7}}},
    ]) == {"marked": 14, "early": 3, "pdrop": 4}


def test_state_records_find_neighbor_states() -> None:
    document = {
        "peers": {
            "fe80::1": {"state": "Established"},
            "fe80::2": {"state": "Idle"},
        }
    }
    assert state_records(document, ("state",)) == [
        ("fe80::1", "Established"),
        ("fe80::2", "Idle"),
    ]


def test_state_records_prefer_peer_address_in_bfd_records() -> None:
    assert state_records(
        [{"peer": "fe80::1", "status": "up"}], ("status", "state")
    ) == [("fe80::1", "up")]


def test_root_qdisc_drops_ignore_child_qdiscs() -> None:
    assert root_qdisc_drops([
        {"kind": "tbf", "root": True, "drops": 7},
        {"kind": "bfifo", "parent": "8001:1", "drops": 3},
    ]) == 7


def test_host_tcp_counters_parse_nstat() -> None:
    assert host_tcp_counters("#kernel\nTcpOutSegs   120  0.0\nTcpRetransSegs  4  0.0\n") == {
        "TcpOutSegs": 120,
        "TcpRetransSegs": 4,
    }
