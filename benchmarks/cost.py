"""$ per 1M output tokens from MEASURED throughput:  $/1M = $/GPU-hour / (tok/s x 3600) x 1e6

    python benchmarks/cost.py --usd-per-hour 0.526 --price-source "<url> (accessed <date>)" --tok-s 31.2
    python benchmarks/cost.py --azure-price-json benchmarks/results/t4/pricing/azure-NC4as_T4_v3-eastus.json \
        --jsonl benchmarks/results/t4/<run>/results/sweep/sweep.jsonl --metric steady_output_tok_s
    python benchmarks/cost.py ... --out benchmarks/results/t4/cost.md

The price is never assumed: give --usd-per-hour (+ --price-source) or a saved Azure Retail Prices API
response (--azure-price-json; the Linux on-demand row is used, Spot/Low Priority/Windows are skipped).
An Azure VM price covers the whole VM (here 1 x T4 + 4 vCPU + 28 GiB), which is what you'd pay to serve.
Throughput comes from result rows (--jsonl, one row per point) or --tok-s; the metric is named in the output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def usd_per_million(usd_per_hour: float, tok_s: float) -> float:
    return usd_per_hour / (tok_s * 3600) * 1e6


def azure_price(path: Path) -> tuple[float, str]:
    d = json.loads(path.read_text())
    rows = [i for i in d["Items"] if i["type"] == "Consumption" and "Windows" not in i["productName"]
            and not any(w in i["meterName"] for w in ("Spot", "Low Priority"))]
    if len(rows) != 1:
        raise SystemExit(f"{path}: expected one Linux on-demand row, found {len(rows)}")
    r = rows[0]
    src = (path.parent / "SOURCE.txt").read_text().strip() if (path.parent / "SOURCE.txt").exists() else str(path)
    return float(r["retailPrice"]), f"Azure {r['armSkuName']} {r['location']} Linux on-demand {r['retailPrice']} {r['currencyCode']}/{r['unitOfMeasure']}; {src}"


def label(row: dict) -> str:
    parts = [row.get("key", "")]
    for k in ("variant", "model", "concurrency"):
        if row.get(k) is not None and str(row[k]) not in parts[0]:
            parts.append(f"{k}={row[k]}")
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    price = ap.add_mutually_exclusive_group(required=True)
    price.add_argument("--usd-per-hour", type=float, help="on-demand $/GPU-hour (requires --price-source)")
    price.add_argument("--azure-price-json", type=Path, help="saved Azure Retail Prices API response")
    ap.add_argument("--price-source", help="URL + access date for --usd-per-hour")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--tok-s", type=float, nargs="+", help="measured output tok/s value(s)")
    src.add_argument("--jsonl", type=Path, nargs="+", help="result JSONL file(s); rows with --metric are used")
    ap.add_argument("--metric", default="steady_output_tok_s", help="row field holding output tok/s")
    ap.add_argument("--key-prefix", default="", help="only rows whose key starts with this")
    ap.add_argument("--out", type=Path, help="also write the table as Markdown")
    a = ap.parse_args()
    if a.usd_per_hour is not None:
        if not a.price_source:
            ap.error("--usd-per-hour needs --price-source (URL + access date)")
        usd, cite = a.usd_per_hour, a.price_source
    else:
        usd, cite = azure_price(a.azure_price_json)

    points: list[tuple[str, float, str]] = []
    if a.tok_s:
        points = [(f"tok_s={v}", v, "--tok-s") for v in a.tok_s]
    else:
        for f in a.jsonl:
            for line in f.read_text().splitlines():
                row = json.loads(line)
                if row.get("key", "").startswith(a.key_prefix) and isinstance(row.get(a.metric), (int, float)) and row[a.metric] > 0:
                    points.append((label(row), row[a.metric], str(f)))
    lines = [f"Price: ${usd}/h — {cite}", f"Formula: $/1M output tokens = {usd} / (tok/s × 3600) × 1e6; tok/s = `{a.metric}`", "",
             f"| point | {a.metric} | $/1M output tokens | source |", "|---|---:|---:|---|"]
    for name, tok_s, f in points:
        lines.append(f"| {name} | {tok_s:g} | {usd_per_million(usd, tok_s):.3f} | {f} |")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.out:
        a.out.write_text(text)


if __name__ == "__main__":
    main()
