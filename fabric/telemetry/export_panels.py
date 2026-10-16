"""Export fabric dashboard query results from the local standalone Prometheus."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "observability" / "dashboards" / "fabric.json"


def query_range(
    base_url: str, expression: str, start: float, end: float, step: str
) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "query": expression,
        "start": start,
        "end": end,
        "step": step,
    })
    url = f"{base_url.rstrip('/')}/api/v1/query_range?{params}"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.load(response)
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload!r}")
    return payload["data"]["result"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--end", type=float, help="Unix end timestamp; defaults to now")
    parser.add_argument("--step", default="10s")
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.minutes <= 0:
        parser.error("--minutes must be positive")
    end = args.end or time.time()
    start = end - args.minutes * 60
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "label": "EMULATED Linux/veth telemetry; not switch ASIC statistics",
        "exported_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "window_unix": [start, end],
        "window_local": [
            dt.datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
            for value in (start, end)
        ],
        "prometheus": "http://127.0.0.1:9098",
        "panels": [],
    }
    for panel in dashboard["panels"]:
        if panel["type"] == "row":
            continue
        output_panel = {"title": panel["title"], "queries": []}
        for target in panel["targets"]:
            series = query_range(
                result["prometheus"], target["expr"], start, end, args.step
            )
            output_series = []
            for item in series:
                samples = [
                    float(value)
                    for _, value in item["values"]
                    if value not in ("NaN", "+Inf", "-Inf")
                ]
                output_series.append({
                    "labels": item["metric"],
                    "points": len(item["values"]),
                    "min": min(samples) if samples else None,
                    "max": max(samples) if samples else None,
                    "last": samples[-1] if samples else None,
                })
            output_panel["queries"].append({
                "legend": target["legendFormat"],
                "expression": target["expr"],
                "series": output_series,
            })
        result["panels"].append(output_panel)
    output = Path(args.out) if args.out else (
        ROOT / "fabric" / "telemetry" / "e5-panels.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote dashboard query evidence to {output}")


if __name__ == "__main__":
    main()
