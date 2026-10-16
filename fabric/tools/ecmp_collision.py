"""ECMP collision calculator (CALCULATED, not measured).

Models static per-flow ECMP as "k equal flows thrown independently and uniformly
onto n equal links" (balls into bins). For a synchronized collective, job time is
set by the busiest link, so the slowdown versus a perfect split is

    slowdown = max_link_flows / ceil(k / n)

Outputs, per (flows k, links n):
  p_no_collision  exact: n! / ((n-k)! * n^k)   (0 when k > n)
  p_perfect       exact: P(max load == ceil(k/n)), by enumeration of load vectors
  mean_slowdown   exact expectation of the slowdown above
  p95_slowdown    exact 95th percentile of the slowdown

Usage:
  python -m fabric.tools.ecmp_collision                 # default table
  python -m fabric.tools.ecmp_collision --flows 2 4 8 16 32 64 --links 2 8
"""
from __future__ import annotations

import argparse
import math
from functools import lru_cache


def p_no_collision(k: int, n: int) -> float:
    if k > n:
        return 0.0
    return math.perm(n, k) / n**k


def max_load_distribution(k: int, n: int) -> dict[int, float]:
    """Exact P(max load = m) for k balls in n bins, via counting surjection-free
    placements with every bin <= m (dynamic programming over bins)."""

    @lru_cache(maxsize=None)
    def ways_le(m: int, balls: int, bins: int) -> int:
        # number of ordered placements of `balls` labelled balls into `bins`
        # labelled bins with every bin holding <= m balls
        if bins == 0:
            return 1 if balls == 0 else 0
        total = 0
        for b in range(0, min(m, balls) + 1):
            total += math.comb(balls, b) * ways_le(m, balls - b, bins - 1)
        return total

    total = n**k
    dist: dict[int, float] = {}
    prev = 0
    for m in range(0, k + 1):
        cur = ways_le(m, k, n)
        if cur - prev:
            dist[m] = (cur - prev) / total
        prev = cur
        if cur == total:
            break
    return dist


def summarize(k: int, n: int) -> dict[str, float]:
    ideal = math.ceil(k / n)
    dist = max_load_distribution(k, n)
    mean = sum(m * p for m, p in dist.items()) / ideal
    acc, p95 = 0.0, None
    for m in sorted(dist):
        acc += dist[m]
        if acc >= 0.95 and p95 is None:
            p95 = m / ideal
    return {
        "p_no_collision": p_no_collision(k, n),
        "p_perfect": dist.get(ideal, 0.0),
        "mean_slowdown": mean,
        "p95_slowdown": p95,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--flows", type=int, nargs="+", default=[1, 2, 4, 8, 16, 32, 64])
    ap.add_argument("--links", type=int, nargs="+", default=[2, 8])
    a = ap.parse_args()
    print("CALCULATED — static per-flow ECMP, equal flows, uniform independent hashing\n")
    print("| links | flows | P(no collision) | P(perfect split) | mean slowdown | p95 slowdown |")
    print("|---:|---:|---:|---:|---:|---:|")
    for n in a.links:
        for k in a.flows:
            s = summarize(k, n)
            print(f"| {n} | {k} | {s['p_no_collision']:.4f} | {s['p_perfect']:.4f} | "
                  f"{s['mean_slowdown']:.2f}x | {s['p95_slowdown']:.2f}x |")


if __name__ == "__main__":
    main()
