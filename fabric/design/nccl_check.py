"""MEASURED 2-GPU NCCL all-reduce (Kaggle 2 x T4, PCIe, one box) against the CALCULATED alpha-beta model.

This is GPU collective communication between two GPUs in one VM over PCIe. It is not the scale-out
fabric and not NVLink. What it checks: the shape T = alpha * steps + bytes / bandwidth and the nccl-tests
bus-bandwidth accounting that collectives.py uses (sources.md S15). Write-up: nccl_check.md.

    python -m fabric.design.nccl_check --run benchmarks/results/t4/<run-id>_nccl [--write]

--write replaces the marked tables in fabric/design/nccl_check.md.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

import yaml

from fabric.design.collectives import DEFAULT_CONFIG, Link, ring_allreduce_time, table, tree_allreduce_time

REPO = Path(__file__).resolve().parents[2]
DOC = Path(__file__).with_name("nccl_check.md")
# Per-lane transfer rate (GT/s) and line-code efficiency per PCIe generation (sources.md S21).
PCIE = {1: (2.5, 8 / 10), 2: (5.0, 8 / 10), 3: (8.0, 128 / 130), 4: (16.0, 128 / 130), 5: (32.0, 128 / 130)}
SMALL_MAX_B = 1024          # "small message": sizes up to 1 KiB are latency-bound
TABLE_SIZES = [8, 1024, 8192, 65536, 2**20, 8 * 2**20, 64 * 2**20, 2**30]


def pcie_bytes_per_s(gen: int, width: int) -> float:
    """Raw per-direction payload rate after line coding: GT/s * lanes * code efficiency / 8 bits."""
    gt, code = PCIE[gen]
    return gt * 1e9 * width * code / 8


def load_rows(run: Path) -> dict[str, dict]:
    f = run / "results" / "nccl" / "nccl.jsonl"
    rows: dict[str, dict] = {}
    for line in f.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["key"]] = r
    return rows


def curve(rows: list[dict], half: str = "oop") -> dict[int, float]:
    """size -> median time (us) over the given runs (out-of-place by default)."""
    by: dict[int, list[float]] = {}
    for r in rows:
        for p in r.get("points", []):
            if p[half]["time_us"] is not None:
                by.setdefault(p["size_b"], []).append(p[half]["time_us"])
    return {s: statistics.median(v) for s, v in sorted(by.items())}


def busbw_at(r: dict, size: int, half: str = "oop") -> float | None:
    return next((p[half]["busbw_gbs"] for p in r.get("points", []) if p["size_b"] == size), None)


def fit(sizes_times: dict[int, float]) -> dict:
    """Two fits of T(S) = t0 + S / B to measured (size B, time us):
    - endpoints: t0 = median time of sizes <= 1 KiB, B = largest size / its time (the large-message algbw);
    - least squares on relative error (weights 1/T^2), so small and large sizes count equally.
    The bend is where the two terms are equal: S* = t0 * B."""
    small = [t for s, t in sizes_times.items() if s <= SMALL_MAX_B]
    big = max(sizes_times)
    t0 = statistics.median(small) * 1e-6
    b_end = big / (sizes_times[big] * 1e-6)
    # weighted least squares: minimise sum ((t0 + c*S - T) / T)^2 -> 2x2 normal equations
    a11 = a12 = a22 = y1 = y2 = 0.0
    for s, t_us in sizes_times.items():
        t = t_us * 1e-6
        w = 1 / t**2
        a11 += w
        a12 += w * s
        a22 += w * s * s
        y1 += w * t
        y2 += w * s * t
    det = a11 * a22 - a12 * a12
    t0_ls = (y1 * a22 - y2 * a12) / det
    c_ls = (a11 * y2 - a12 * y1) / det
    return {"t0_s": t0, "bytes_per_s": b_end, "bend_b": t0 * b_end,
            "ls_t0_s": t0_ls, "ls_bytes_per_s": 1 / c_ls if c_ls > 0 else None,
            "ls_bend_b": t0_ls / c_ls if c_ls > 0 else None, "small_n": len(small)}


def human(b: float) -> str:
    for unit, k in (("GiB", 2**30), ("MiB", 2**20), ("KiB", 2**10)):
        if b >= k:
            return f"{b / k:,.4g} {unit}"
    return f"{b:,.0f} B"


def pct(model: float, meas: float) -> str:
    return f"{(model - meas) / meas:+.0%}"


def check(run: Path, cfg_path: Path = DEFAULT_CONFIG) -> dict:
    rows = load_rows(run)
    probe = rows["probe"]
    defaults = [r for k, r in rows.items() if re.fullmatch(r"allreduce-default-r\d+", k) and r.get("points")]
    if not defaults:
        raise SystemExit(f"{run}: no allreduce-default-r* rows with data")
    meas = curve(defaults)
    f = fit(meas)
    cfg = yaml.safe_load(cfg_path.read_text())
    # PCIe link while traffic flowed (link gen can drop at idle), from the first default run
    link = (defaults[0].get("pcie_during") or probe.get("pcie_idle") or [{}])[0]
    gen, width = int(link["pcie.link.gen.current"]), int(link["pcie.link.width.current"])
    pcie = pcie_bytes_per_s(gen, width)
    # Defaults: collectives.py has no PCIe entry; the intra-box (scale-up) defaults are A2 (eff 0.80) and A4 (1 us)
    eff, alpha = cfg["efficiency"]["nvlink"], cfg["alpha_us"]["nvlink"] * 1e-6
    link_def = Link(pcie * eff, alpha)
    # Fitted: alpha = small-message time / 2 steps (ring, N = 2: 2(N-1) = 2), bandwidth = large-message busbw
    link_fit = Link(f["bytes_per_s"], f["t0_s"] / 2)
    errs = {"defaults": [], "fitted": []}
    for s, t_us in meas.items():
        m = t_us * 1e-6
        errs["defaults"].append((ring_allreduce_time(2, s, link_def) - m) / m)
        errs["fitted"].append((ring_allreduce_time(2, s, link_fit) - m) / m)
    out_rows = []
    for s in TABLE_SIZES:
        if s not in meas:
            continue
        m = meas[s] * 1e-6
        d, ft = ring_allreduce_time(2, s, link_def), ring_allreduce_time(2, s, link_fit)
        out_rows.append({"size_b": s, "measured_s": m, "model_default_s": d, "model_fit_s": ft,
                         "err_default": (d - m) / m, "err_fit": (ft - m) / m,
                         "tree_default_s": tree_allreduce_time(2, s, link_def)})
    return {"run": str(run.relative_to(REPO)) if run.is_absolute() else str(run), "pcie_gen": gen,
            "pcie_width": width, "pcie_bytes_per_s": pcie, "eff_default": eff, "alpha_default_s": alpha,
            "fit": f, "rows": out_rows, "repeats": len(defaults), "n_sizes": len(meas),
            "err_abs_max": {k: max(abs(e) for e in v) for k, v in errs.items()},
            "err_abs_median": {k: statistics.median(abs(e) for e in v) for k, v in errs.items()},
            "algo_by_size": defaults[0].get("algo_by_size", {}).get("AllReduce", {}),
            "busbw_1g": [busbw_at(r, 2**30) for r in defaults],
            "algbw_1g": [next((p["oop"]["algbw_gbs"] for p in r["points"] if p["size_b"] == 2**30), None) for r in defaults]}


def us(x: float) -> str:
    return f"{x * 1e6:,.1f}"


def markdown(c: dict) -> str:
    f = c["fit"]
    body = [[human(r["size_b"]), us(r["measured_s"]), us(r["model_default_s"]), us(r["model_fit_s"]),
             pct(r["model_default_s"], r["measured_s"]), pct(r["model_fit_s"], r["measured_s"])] for r in c["rows"]]
    t = table(["Size", "Measured (µs, median of %d)" % c["repeats"], "Model, defaults (µs)", "Model, fitted (µs)",
               "Error, defaults", "Error, fitted"], body)
    ls = (f"Least-squares cross-check (relative error, all {c['n_sizes']} sizes): t0 = {f['ls_t0_s'] * 1e6:,.1f} µs, "
          f"B = {f['ls_bytes_per_s'] / 1e9:,.2f} GB/s, bend at {human(f['ls_bend_b'])}." if f.get("ls_bytes_per_s") else "")
    return "\n".join([
        f"Run: `{c['run']}`. PCIe link under load: Gen{c['pcie_gen']} x{c['pcie_width']} → "
        f"{c['pcie_bytes_per_s'] / 1e9:,.3f} GB/s per direction (S21). "
        f"Defaults: efficiency {c['eff_default']:.2f} (A2), α = {c['alpha_default_s'] * 1e6:g} µs (A4) → "
        f"B = {c['pcie_bytes_per_s'] * c['eff_default'] / 1e9:,.2f} GB/s. "
        f"Fitted: t0 = {f['t0_s'] * 1e6:,.1f} µs (median, sizes ≤ 1 KiB, n = {f['small_n']}) → α = t0 / 2 = "
        f"{f['t0_s'] / 2 * 1e6:,.1f} µs; B = {f['bytes_per_s'] / 1e9:,.2f} GB/s (1 GiB algbw = busbw at N = 2); "
        f"bend (t0 = S/B) at **{human(f['bend_b'])}**.", "", ls, "",
        f"Over all {c['n_sizes']} sizes (8 B … 1 GiB): |error| median / max = "
        f"{c['err_abs_median']['defaults']:.0%} / {c['err_abs_max']['defaults']:.0%} with defaults, "
        f"{c['err_abs_median']['fitted']:.0%} / {c['err_abs_max']['fitted']:.0%} fitted.", "", t])


def write_doc(md: str) -> None:
    text = DOC.read_text()
    new = re.sub(r"(<!-- nccl-check:table -->\n).*?(<!-- /nccl-check -->)", lambda m: m.group(1) + md + "\n" + m.group(2),
                 text, flags=re.S)
    DOC.write_text(new)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", type=Path, required=True, help="benchmarks/results/t4/<run-id>_nccl")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--write", action="store_true", help="update the table block in nccl_check.md")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    c = check(a.run.resolve(), a.config)
    if a.json:
        print(json.dumps(c, indent=2))
        return
    md = markdown(c)
    print(md)
    if a.write:
        write_doc(md)
        print(f"\nwrote {DOC}", file=sys.stderr)


if __name__ == "__main__":
    main()
