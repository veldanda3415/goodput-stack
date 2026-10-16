"""Hand-computed cases for fabric/design/collectives.py (CALCULATED model, not measurements)."""

from pathlib import Path

import pytest
import yaml

from fabric.design import collectives as c

CFG = yaml.safe_load(Path(c.DEFAULT_CONFIG).read_text())
UNIT = c.Link(bytes_per_s=1000.0, alpha_s=0.0)  # 1,000 B/s, no latency


def test_ring_allreduce_bytes_n2():
    # 2 * (2-1)/2 * 1000 = 1000: each rank sends half, then the other half back.
    assert c.ring_allreduce_bytes(2, 1000) == pytest.approx(1000)


def test_ring_allreduce_bytes_n8():
    # 2 * 7/8 * 800 = 1400
    assert c.ring_allreduce_bytes(8, 800) == pytest.approx(1400)


def test_ring_allreduce_time_n8_with_alpha():
    # 2*(8-1) steps * 1 ms + 1400 B / 1000 B/s = 0.014 + 1.4 = 1.414 s
    link = c.Link(1000.0, 0.001)
    assert c.ring_allreduce_time(8, 800, link) == pytest.approx(1.414)


def test_tree_latency_is_logarithmic():
    # N=256: ring 2*255 = 510 alpha steps; tree 2*log2(256) = 16 alpha steps; same bytes.
    link = c.Link(1e30, 1.0)
    assert c.ring_allreduce_time(256, 1, link) == pytest.approx(510)
    assert c.tree_allreduce_time(256, 1, link) == pytest.approx(16)


def test_reduce_scatter_all_gather_and_all_to_all_bytes():
    # (N-1)/N * S: N=4, S=1000 -> 750; RS + AG = 1500 = ring all-reduce bytes.
    assert c.scatter_gather_bytes(4, 1000) == pytest.approx(750)
    assert 2 * c.scatter_gather_bytes(4, 1000) == pytest.approx(c.ring_allreduce_bytes(4, 1000))


def test_p2p_time():
    assert c.p2p_time(500, c.Link(1000.0, 0.01)) == pytest.approx(0.51)


def test_hierarchical_allreduce_bytes():
    # G=8 local, M=4 nodes, S=800: NVLink 2*7/8*800 = 1400; NIC ring on S/8=100 -> 2*3/4*100 = 150.
    r = c.hierarchical_allreduce(8, 4, 800, UNIT, UNIT)
    assert r.up_bytes == pytest.approx(1400)
    assert r.out_bytes == pytest.approx(150)
    assert r.time_s == pytest.approx((1400 + 150) / 1000)


def test_slow_link_ring_runs_at_slowest_link():
    # N=8 ring, S=800, B=1000, alpha=0: 1.4 s healthy; one link at 50 % -> 2.8 s (x2).
    healthy = c.hierarchical_allreduce(1, 8, 800, UNIT, UNIT)
    slow = c.hierarchical_allreduce(1, 8, 800, UNIT, UNIT, net_rate_fraction=0.5)
    assert healthy.time_s == pytest.approx(1.4)
    assert slow.time_s == pytest.approx(2.8)
    # Job with 1.4 s compute, no overlap: (1.4+2.8)/(1.4+1.4) - 1 = +50 %.
    assert c.slowdown(1.4 + 1.4, 1.4 + 2.8) == pytest.approx(0.5)


def test_kv_bytes_per_token_llama32_3b():
    # 2 * 28 layers * 8 KV heads * 128 head_dim * 2 B = 114,688 (benchmarks/results/t4).
    assert c.kv_bytes_per_token(28, 8, 128, 2) == 114_688


def test_kv_transfer_bandwidth():
    # 114,688 B * 2,048 tokens * 10 req/s * 8 bit = 18.79 Gb/s -> one 400G NIC at 80 %.
    r = c.kv_transfer(CFG, {"model": "llama3.2-3b", "dtype_bytes": 2,
                            "prompt_tokens": 2048, "requests_per_s": 10})
    assert r["per_request"] == 114_688 * 2048
    assert r["gbps"] == pytest.approx(114_688 * 2048 * 10 * 8 / 1e9)
    assert r["nics"] == 1


def test_split_group_placement():
    assert c.split_group(8, 1, 8) == (8, 1)      # TP=8 inside one node
    assert c.split_group(8, 8, 8) == (1, 8)      # DP across 8 nodes, one GPU each (rail)
    assert c.split_group(256, 1, 8) == (8, 32)   # DP=256 with TP=1: hierarchical
    assert c.split_group(8, 2, 8) == (4, 2)      # EP=8 after TP=2: 4 per node, 2 nodes


def test_70b_dp_gradient_bytes():
    # 70e9 params / (TP 8 * PP 4) * 2 B = 4.375 GB; DP=8 across nodes: 2*7/8*4.375 = 7.65625 GB.
    w = next(x for x in CFG["training"] if x["name"] == "70B on 256 GPUs")
    dp = next(r for r in c.training_rows(CFG, w) if r.parallelism == "DP")
    assert dp.network == c.SCALE_OUT
    assert dp.out_bytes == pytest.approx(7.65625e9)


def test_70b_tp_stays_on_nvlink():
    w = next(x for x in CFG["training"] if x["name"] == "70B on 256 GPUs")
    tp = next(r for r in c.training_rows(CFG, w) if r.parallelism == "TP")
    assert tp.network == c.SCALE_UP and tp.out_bytes == 0
    # 4 all-reduces * 80/4 layers * 16 microbatches = 1,280 calls (S17)
    assert tp.calls == 1280


def test_8b_compute_time():
    # 6 * 8e9 * 8192 tokens per GPU / (989.5e12 * 0.40) = 0.99347 s
    w = next(x for x in CFG["training"] if x["name"] == "8B on 256 GPUs")
    assert c.compute_time_s(CFG, w) == pytest.approx(6 * 8e9 * 8192 / (989.5e12 * 0.4))


def test_cli_prints_markdown(capsys):
    c.main(["--section", "inference"])
    out = capsys.readouterr().out
    assert "| llama3.2-3b | 114,688 |" in out and "CALCULATED" in out
