"""Hand-checked cases for fabric/design/scaleout.py (CALCULATED tables, no hardware)."""

from __future__ import annotations

import pytest
import yaml

from fabric.design import scaleout
from fabric.design.collectives import DEFAULT_CONFIG, Link


def cfg() -> dict:
    return yaml.safe_load(DEFAULT_CONFIG.read_text())


def qwen3b() -> scaleout.Model:
    return scaleout.load_model(cfg()["scaleout"]["models"][0])


def test_qwen3b_fields_from_pinned_config():
    m = qwen3b()
    assert (m.layers, m.hidden, m.heads, m.kv_heads, m.head_dim) == (36, 2048, 16, 2, 128)
    assert m.revision == "aa8e72537993ba99e69dfaafa59ed015b17504d1"


def test_kv_bytes_per_token_qwen3b():
    # 36 layers x 2 (K, V) x 2 KV heads x 128 x 2 bytes = 36,864 (the same number the G2 trace used)
    m = qwen3b()
    assert scaleout.kv_bytes_per_token(m.layers, m.kv_heads, m.head_dim, 2) == 36_864


def test_bytes_per_step_hand_checked():
    # Qwen2.5-3B, batch 64, TP 2: message = 64 x 2048 x 2 = 262,144 B; 2 x 36 = 72 all-reduces per step;
    # ring at N = 2 puts 2(N-1)/N = 1 x S on the wire per GPU -> 72 x 262,144 = 18,874,368 B.
    m = qwen3b()
    assert scaleout.tp_message_bytes(m, 64, 2) == 262_144
    assert scaleout.tp_messages_per_step(m) == 72
    assert scaleout.tp_wire_bytes_per_gpu(m, 2, 64, 2) == 18_874_368
    # TP 4: 2 x 3/4 x S per all-reduce -> 72 x 393,216
    assert scaleout.tp_wire_bytes_per_gpu(m, 4, 64, 2) == 72 * 393_216
    # time with B = 4 GB/s, alpha = 10 us: 72 x (2 x 10 us + 262,144 / 4e9 s) = 72 x 85.536 us
    t = scaleout.tp_comm_s(m, 2, 64, 2, Link(4e9, 10e-6))
    assert t == pytest.approx(72 * 85.536e-6)


def test_slow_link_doubles_plain_ring():
    m = qwen3b()
    no_alpha = Link(40e9, 0.0)
    healthy = scaleout.tp_comm_s(m, 8, 384, 2, no_alpha)
    assert scaleout.tp_comm_s(m, 8, 384, 2, no_alpha, 0.5) == pytest.approx(2 * healthy)
    # with alpha, only the bandwidth term doubles
    lk = Link(40e9, 5e-6)
    alpha_part = 72 * 2 * 7 * 5e-6
    assert scaleout.tp_comm_s(m, 8, 384, 2, lk, 0.5) - alpha_part == pytest.approx(
        2 * (scaleout.tp_comm_s(m, 8, 384, 2, lk) - alpha_part))


def test_share_no_overlap():
    assert scaleout.share(1.0, 3.0) == 0.25
    assert scaleout.share(1.0, None) is None


def test_h100_pending_when_empty():
    assert scaleout.h100_ms(cfg()["scaleout"], "Qwen2.5-3B-Instruct", 64) is None


def test_scaleout_md_regenerates_identically():
    assert scaleout.main(["--check"]) == 0
