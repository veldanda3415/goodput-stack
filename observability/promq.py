#!/usr/bin/env python3
"""Query the lab Prometheus from the k3s host (ClusterIPs are routable from the node).

  python3 observability/promq.py targets                 # every active target: health, pool, last error
  python3 observability/promq.py targets --wait inference # block until every target in ns inference is up
  python3 observability/promq.py query 'up{namespace="inference"}'
  python3 observability/promq.py alerts                  # active alerts and their state (pending/firing)

The Prometheus URL is resolved from the Service (kps-kube-prometheus-stack-prometheus) unless --url is given.
stdlib only.
"""
import argparse, json, subprocess, sys, time, urllib.parse, urllib.request

SVC_NS, SVC = "monitoring", "kps-kube-prometheus-stack-prometheus"


def prom_url() -> str:
    ip = subprocess.run(["kubectl", "-n", SVC_NS, "get", "svc", SVC, "-o", "jsonpath={.spec.clusterIP}"],
                        check=True, capture_output=True, text=True).stdout
    return f"http://{ip}:9090"


def get(url: str, path: str, **params) -> dict:
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}{path}?{q}", timeout=10) as r:
        return json.load(r)["data"]


def targets(url: str, ns: str | None) -> list[dict]:
    out = []
    for t in get(url, "/api/v1/targets", state="active")["activeTargets"]:
        lbl = t["labels"]
        if ns and lbl.get("namespace") != ns:
            continue
        out.append({"health": t["health"], "job": lbl.get("job", ""), "pool": lbl.get("pool", ""),
                    "url": t["scrapeUrl"], "error": t.get("lastError", "")})
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("targets")
    t.add_argument("--ns")
    t.add_argument("--wait", metavar="NS", help="poll until every target in NS is up (max --timeout s)")
    t.add_argument("--timeout", type=float, default=120)
    q = sub.add_parser("query")
    q.add_argument("expr")
    sub.add_parser("alerts")
    a = p.parse_args()
    url = a.url or prom_url()

    if a.cmd == "targets":
        ns = a.wait or a.ns
        deadline = time.monotonic() + a.timeout
        while True:
            ts = targets(url, ns)
            if not a.wait or (ts and all(x["health"] == "up" for x in ts)) or time.monotonic() > deadline:
                break
            time.sleep(3)
        for x in ts:
            print(f'{x["health"]:<8}{x["job"]:<20}{x["pool"]:<15}{x["url"]:<42}{x["error"]}')
        return 0 if all(x["health"] == "up" for x in ts) else 1
    if a.cmd == "query":
        d = get(url, "/api/v1/query", query=a.expr)
        for r in d["result"]:
            print(json.dumps(r["metric"], sort_keys=True), r["value"][1])
        return 0
    if a.cmd == "alerts":
        for al in get(url, "/api/v1/alerts")["alerts"]:
            print(al["state"], al.get("activeAt", ""), json.dumps(al["labels"], sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
