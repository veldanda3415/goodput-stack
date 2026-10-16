"""Parser and fit for the 2 x T4 NCCL check, on saved real outputs (tests/data/, from run 20261016-153016_nccl)."""

from pathlib import Path

import pytest

from benchmarks.kaggle.t4_notebook import parse_nccl_debug, parse_nccl_tests
from fabric.design import nccl_check as nc

DATA = Path(__file__).with_name("data")
AR = (DATA / "nccl_all_reduce_perf_2xT4.log").read_text()
AG = (DATA / "nccl_all_gather_perf_2xT4.log").read_text()
DBG = (DATA / "nccl_debug_all_reduce_2xT4.txt").read_text()


def test_all_reduce_rows():
    r = parse_nccl_tests(AR)
    assert len(r["points"]) == 28                      # 8 B .. 1 GiB, factor 2
    first, last = r["points"][0], r["points"][-1]
    assert (first["size_b"], first["count"], first["type"], first["redop"], first["root"]) == (8, 2, "float", "sum", -1)
    assert first["oop"] == {"time_us": 16.59, "algbw_gbs": 0.0, "busbw_gbs": 0.0, "wrong": 0}
    assert first["ip"]["time_us"] == 16.64
    assert last["size_b"] == 2**30
    assert last["oop"]["busbw_gbs"] == 3.91
    assert r["wrong_total"] == 0 and r["oob_status"] == "OK"
    assert r["nccl_library_code"] == 22809 and r["nccl_tests_version"] == "2.21.0"


def test_all_reduce_busbw_equals_algbw_at_n2():
    # all-reduce busbw = algbw * 2(N-1)/N = algbw for N = 2 (nccl-tests PERFORMANCE.md)
    for p in parse_nccl_tests(AR)["points"]:
        assert p["oop"]["busbw_gbs"] == p["oop"]["algbw_gbs"]


def test_all_gather_busbw_is_half_algbw_at_n2():
    # all-gather busbw = algbw * (N-1)/N = algbw / 2 for N = 2; printed with 2 decimals
    pts = [p for p in parse_nccl_tests(AG)["points"] if p["oop"]["algbw_gbs"] >= 1]
    assert pts
    for p in pts:
        assert p["oop"]["busbw_gbs"] == pytest.approx(p["oop"]["algbw_gbs"] / 2, abs=0.006)


def test_rows_survive_interleaved_lines():
    # the smoke run showed NCCL INFO text splitting rows; such lines are skipped, clean rows still parse
    mixed = AR.replace("\n          16 ", "\nhost:1:1 [0] NCCL INFO noise\n          16 ", 1)
    assert len(parse_nccl_tests(mixed)["points"]) == 28


def test_debug_facts():
    d = parse_nccl_debug(DBG)
    assert d["nccl_version_log"] == "2.28.9+cuda12.9"
    assert d["transports"] == ["SHM/direct/direct"]
    assert d["coll_channels"] == [2]
    ar = d["algo_by_size"]["AllReduce"]
    assert ar["8"] == "RING/LL/ch1"
    assert ar[str(2**30)] == "RING/SIMPLE/ch2"
    assert any(l.startswith("AllReduce |") for l in d["tuning_table"])


def test_fit_on_saved_sample():
    pts = parse_nccl_tests(AR)["points"]
    curve = {p["size_b"]: p["oop"]["time_us"] for p in pts}
    f = nc.fit(curve)
    small = sorted(t for s, t in curve.items() if s <= 1024)       # 8 sizes: 8 B .. 1 KiB
    assert f["t0_s"] == pytest.approx((small[3] + small[4]) / 2 * 1e-6)
    assert f["bytes_per_s"] == pytest.approx(2**30 / (curve[2**30] * 1e-6))
    assert f["bend_b"] == pytest.approx(f["t0_s"] * f["bytes_per_s"])
    assert 32 * 1024 < f["bend_b"] < 128 * 1024                     # where the curve bends on this run
    assert f["ls_bytes_per_s"] == pytest.approx(f["bytes_per_s"], rel=0.1)


def test_fit_recovers_exact_line():
    t0, b = 20e-6, 4e9
    curve = {s: (t0 + s / b) * 1e6 for s in [2**k for k in range(3, 31)]}
    f = nc.fit(curve)
    assert f["ls_t0_s"] == pytest.approx(t0, rel=1e-6)
    assert f["ls_bytes_per_s"] == pytest.approx(b, rel=1e-6)


def test_pcie_rate():
    # Gen3 x16: 8 GT/s * 16 lanes * 128/130 / 8 = 15.754 GB/s per direction (sources.md S21)
    assert nc.pcie_bytes_per_s(3, 16) == pytest.approx(15.754e9, rel=1e-4)
    assert nc.pcie_bytes_per_s(1, 16) == pytest.approx(4.0e9)
