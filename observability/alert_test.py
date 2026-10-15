#!/usr/bin/env python3
"""Prove the EPP alerts fire: scale one EPP to 0 under light traffic, watch Pending -> Firing, restore.

  python3 observability/alert_test.py [--epp sim-pool-epp] [--down-max 150]

Phases: baseline (EPP up, --baseline s) -> EPP scaled to 0 until EPPUnavailable is firing (max --down-max s)
-> scaled back to 1 -> wait until the alerts are gone (max --resolve-max s). Throughout, one sequential client
sends short requests through the gateway to the EPP's pool (status codes counted per phase), and
/api/v1/alerts is polled every 2 s; every state change of an EPP* alert is logged with a timestamp.
Also records agentgateway_request_processing_seconds (sum/count delta per phase) for the pool's route,
to see whether the gateway's pre-upstream processing time includes the EPP ext-proc call.
The EPP is ALWAYS scaled back to its original replica count (finally).
Output: observability/evidence/alert-test-<ts>.jsonl + a summary on stdout. stdlib only.
"""
import argparse, datetime as dt, json, pathlib, re, subprocess, threading, time, urllib.request

NS, MODEL, GW = "inference", "qwen2.5-0.5b-instruct", "http://192.168.117.204"


def kubectl(*a, ns=NS):
    return subprocess.run(["kubectl", "-n", ns, *a], check=True, capture_output=True, text=True).stdout


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def http_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def gw_processing(gw_ip, pool):
    """(sum, count) of agentgateway_request_processing_seconds for route inference/<pool>."""
    txt = urllib.request.urlopen(f"http://{gw_ip}:15020/metrics", timeout=5).read().decode()
    s = c = 0.0
    for m in re.finditer(r'^agentgateway_request_processing_seconds_(sum|count)\{([^}]*)\}\s+(\S+)', txt, re.M):
        if f'route="inference/{pool}"' in m.group(2):
            if m.group(1) == "sum":
                s += float(m.group(3))
            else:
                c += float(m.group(3))
    return s, c


class Traffic(threading.Thread):
    def __init__(self, pool_header):
        super().__init__(daemon=True)
        self.hdr, self.phase, self.stop, self.codes = pool_header, "baseline", False, {}

    def run(self):
        body = json.dumps({"model": MODEL, "max_tokens": 3, "messages": [{"role": "user", "content": "ping"}]}).encode()
        while not self.stop:
            req = urllib.request.Request(f"{GW}/v1/chat/completions", data=body,
                                         headers={"content-type": "application/json", **self.hdr})
            try:
                code = urllib.request.urlopen(req, timeout=10).status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:
                code = type(e).__name__
            k = (self.phase, str(code))
            self.codes[k] = self.codes.get(k, 0) + 1
            time.sleep(0.5)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epp", default="sim-pool-epp")
    p.add_argument("--baseline", type=float, default=30)
    p.add_argument("--down-max", type=float, default=150)
    p.add_argument("--resolve-max", type=float, default=150)
    a = p.parse_args()
    pool = a.epp.removesuffix("-epp")
    hdr = {"x-pool": "cpu"} if pool == "llamacpp-pool" else {}
    prom = "http://" + kubectl("get", "svc", "kps-kube-prometheus-stack-prometheus", "-o",
                               "jsonpath={.spec.clusterIP}", ns="monitoring") + ":9090"
    gw_ip = json.loads(kubectl("get", "pods", "-l", "gateway.networking.k8s.io/gateway-name=inference-gateway",
                               "-o", "json"))["items"][0]["status"]["podIP"]
    orig = int(kubectl("get", "deploy", a.epp, "-o", "jsonpath={.spec.replicas}"))
    out = pathlib.Path("observability/evidence") / f"alert-test-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.open("w")

    def rec(**kw):
        kw = {"t": now(), **kw}
        log.write(json.dumps(kw) + "\n"); log.flush()
        print(json.dumps(kw))

    seen = {}

    def poll_alerts():
        for al in http_json(f"{prom}/api/v1/alerts")["data"]["alerts"]:
            name = al["labels"].get("alertname", "")
            if not name.startswith("EPP"):
                continue
            key = (name, al["labels"].get("deployment") or al["labels"].get("pool") or al["labels"].get("job"))
            if seen.get(key) != al["state"]:
                seen[key] = al["state"]
                rec(event="alert", alert=name, target=key[1], state=al["state"], activeAt=al.get("activeAt"))
        return seen

    tr = Traffic(hdr); tr.start()
    proc = {}
    try:
        rec(event="start", epp=a.epp, pool=pool, original_replicas=orig, prometheus=prom)
        p0 = gw_processing(gw_ip, pool)
        time.sleep(a.baseline)
        proc["baseline"] = (p0, gw_processing(gw_ip, pool))
        tr.phase = "epp_down"
        kubectl("scale", "deploy", a.epp, "--replicas=0")
        t_down = time.monotonic()
        rec(event="scaled", replicas=0)
        p1 = gw_processing(gw_ip, pool)
        firing_at = None
        while time.monotonic() - t_down < a.down_max:
            s = poll_alerts()
            if s.get(("EPPUnavailable", a.epp)) == "firing" and firing_at is None:
                firing_at = time.monotonic() - t_down
                rec(event="firing", alert="EPPUnavailable", seconds_after_scale=round(firing_at, 1))
            if firing_at and all(v == "firing" for k, v in s.items() if k[1] in (a.epp, pool)) and \
                    time.monotonic() - t_down > firing_at + 20:
                break
            time.sleep(2)
        proc["epp_down"] = (p1, gw_processing(gw_ip, pool))
    finally:
        tr.phase = "restored"
        kubectl("scale", "deploy", a.epp, f"--replicas={orig}")
        rec(event="scaled", replicas=orig)
        kubectl("rollout", "status", "deploy", a.epp, "--timeout=120s")
        rec(event="epp_ready")
    t_up = time.monotonic()
    while time.monotonic() - t_up < a.resolve_max:
        poll_alerts()
        live = {(al["labels"]["alertname"]) for al in http_json(f"{prom}/api/v1/alerts")["data"]["alerts"]
                if al["labels"].get("alertname", "").startswith("EPP")}
        if not live:
            rec(event="resolved", seconds_after_restore=round(time.monotonic() - t_up, 1))
            break
        time.sleep(2)
    tr.stop = True; tr.join(timeout=15)
    for ph, ((s0, c0), (s1, c1)) in proc.items():
        n = c1 - c0
        rec(event="gw_request_processing", phase=ph, requests=n,
            mean_ms=round((s1 - s0) / n * 1000, 3) if n else None)
    rec(event="codes", codes={f"{k[0]}:{k[1]}": v for k, v in sorted(tr.codes.items())})
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
