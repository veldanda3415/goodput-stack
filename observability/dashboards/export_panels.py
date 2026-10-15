#!/usr/bin/env python3
"""Run every panel query of inference.json against Prometheus over a window and save the results.

  python3 observability/dashboards/export_panels.py --minutes 10 [--out observability/evidence/panels-<ts>.json]

Evidence that the dashboard has data (no image renderer on this lab, so no PNG). Per query it records
the expression, the series returned, and for each series min / max / last over the window. A query that
returns nothing is listed as such: that is a result (e.g. KV usage for llamacpp-pool does not exist).
stdlib only.
"""
import argparse, datetime as dt, json, pathlib, subprocess, time, urllib.parse, urllib.request

HERE = pathlib.Path(__file__).parent


def prom_url():
    ip = subprocess.run(["kubectl", "-n", "monitoring", "get", "svc", "kps-kube-prometheus-stack-prometheus",
                         "-o", "jsonpath={.spec.clusterIP}"], check=True, capture_output=True, text=True).stdout
    return f"http://{ip}:9090"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=10)
    p.add_argument("--end", type=float, help="unix end time (default now)")
    p.add_argument("--step", default="15s")
    p.add_argument("--out")
    p.add_argument("--panel", help="only panels whose title contains this")
    a = p.parse_args()
    url = prom_url()
    end = a.end or time.time()
    start = end - a.minutes * 60
    dash = json.loads((HERE / "inference.json").read_text())
    res = {"exported_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "window": [dt.datetime.fromtimestamp(start).astimezone().isoformat(timespec="seconds"),
                      dt.datetime.fromtimestamp(end).astimezone().isoformat(timespec="seconds")],
           "prometheus": url, "panels": []}
    for pn in dash["panels"]:
        if pn["type"] == "row" or (a.panel and a.panel not in pn["title"]):
            continue
        entry = {"title": pn["title"], "queries": []}
        for t in pn["targets"]:
            qs = urllib.parse.urlencode({"query": t["expr"], "start": start, "end": end, "step": a.step})
            d = json.load(urllib.request.urlopen(f"{url}/api/v1/query_range?{qs}", timeout=20))["data"]["result"]
            series = []
            for s in d:
                vals = [float(v) for _, v in s["values"] if v not in ("NaN", "+Inf", "-Inf")]
                series.append({"metric": s["metric"], "points": len(s["values"]),
                               "min": min(vals) if vals else None, "max": max(vals) if vals else None,
                               "last": vals[-1] if vals else None})
            entry["queries"].append({"legend": t["legendFormat"], "expr": t["expr"], "series": series})
        res["panels"].append(entry)
    out = pathlib.Path(a.out or f"observability/evidence/panels-{dt.datetime.now():%Y%m%d-%H%M%S}.json")
    out.write_text(json.dumps(res, indent=1) + "\n")
    for pn in res["panels"]:
        print(f'== {pn["title"]}')
        for q in pn["queries"]:
            if not q["series"]:
                print(f'   {q["legend"]:<45} NO DATA')
            for s in q["series"]:
                lbl = s["metric"].get("pool") or s["metric"].get("deployment") or s["metric"].get("pod") or s["metric"].get("name") or ""
                fmt = lambda v: "-" if v is None else f"{v:.4g}"
                print(f'   {q["legend"]:<45} {lbl:<22} min {fmt(s["min"]):>9} max {fmt(s["max"]):>9} last {fmt(s["last"]):>9}')
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
