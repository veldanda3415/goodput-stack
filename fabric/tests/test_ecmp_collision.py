"""Unit tests for the ECMP collision calculator (no lab needed)."""
import math
import random

import pytest

from fabric.tools.ecmp_collision import max_load_distribution, p_no_collision, summarize


def test_birthday_closed_forms():
    assert p_no_collision(2, 2) == 0.5
    assert p_no_collision(8, 8) == pytest.approx(math.factorial(8) / 8**8)
    assert p_no_collision(3, 2) == 0.0


def test_distribution_sums_to_one():
    for k, n in [(1, 2), (4, 2), (8, 8), (16, 8)]:
        assert sum(max_load_distribution(k, n).values()) == pytest.approx(1.0)


def test_two_flows_two_links():
    s = summarize(2, 2)
    assert s["p_perfect"] == 0.5 and s["mean_slowdown"] == 1.5 and s["p95_slowdown"] == 2.0


def test_matches_monte_carlo():
    rng = random.Random(0)
    k, n, trials = 8, 8, 20000
    total = 0.0
    for _ in range(trials):
        counts = [0] * n
        for _ in range(k):
            counts[rng.randrange(n)] += 1
        total += max(counts)
    assert summarize(k, n)["mean_slowdown"] == pytest.approx(total / trials, rel=0.02)
