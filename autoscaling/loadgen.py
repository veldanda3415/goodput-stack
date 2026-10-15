#!/usr/bin/env python3
"""Step load (idle -> high -> idle) through the gateway against one pool, with a timestamped scaling log.

  .venv/bin/python autoscaling/loadgen.py --pool sim  --concurrency 8 --max-tokens 96    # sim-pool (SIMULATED)
  .venv/bin/python autoscaling/loadgen.py --pool cpu  --concurrency 6 --max-tokens 64    # llamacpp-pool

Phases: idle (--idle s, no requests) -> high (--high s, --concurrency streams, each sending requests back to
back with unique prompts) -> idle until the deployment is back at --settle-replicas for 20 s (max --tail s).

Every second a sampler records (k3s host: pod IPs are routable):
  deployment spec/ready replicas, the KEDA HPA's desiredReplicas, every pod (created, Ready, IP), and a direct
  /metrics scrape of each pod: queue = running + waiting (the ScaledObject's metric) and whether it has served
  anything yet (sim: vllm:request_success_total > 0 or running > 0; llama.cpp: tokens_predicted_total > 0 or
  requests_processing > 0). From that it logs events: load start/stop, HPA desired change (= the scaling
  decision as the HPA sees it), pod created, pod Ready, first request served by a new pod, pod deleted.
Client side: per request send time, TTFT (first non-empty delta.content, scripts/stream_client.stream_chat), total, error.
At the end: HPA events (SuccessfulRescale) and KEDA operator log lines for the ScaledObject are saved, and a
10 s step table (replicas, queue, requests, errors, client TTFT p50/p95) is printed and written to summary.md.

Output: autoscaling/results/<ts>-<pool>/{log.jsonl,requests.jsonl,samples.jsonl,hpa-events.txt,keda.log,summary.md}
"""
import argparse, asyncio, datetime as dt, json, pathlib, re, statistics, subprocess, sys, threading, time, urllib.request
import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
from stream_client import stream_chat  # noqa: E402

NS, MODEL, GW = "inference", "qwen2.5-0.5b-instruct", "http://192.168.117.204"
POOLS = {
    "sim": dict(pool="sim-pool", deploy="inf-vllm-sim", so="inf-vllm-sim", port=8000, headers={},
                queue=("vllm:num_requests_running", "vllm:num_requests_waiting"),
                served=("vllm:request_success_total", "vllm:num_requests_running")),
    "cpu": dict(pool="llamacpp-pool", deploy="inf-llamacpp", so="inf-llamacpp", port=8080, headers={"x-pool": "cpu"},
                queue=("llamacpp:requests_processing", "llamacpp:requests_deferred"),
                served=("llamacpp:tokens_predicted_total", "llamacpp:requests_processing")),
}


def ts():
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def kubectl_json(*a):
    r = subprocess.run(["kubectl", "-n", NS, *a, "-o", "json"], capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout) if r.returncode == 0 else None


def scrape(ip, port, names):
    """sum of each metric name across its series; None if unreachable."""
    try:
        txt = urllib.request.urlopen(f"http://{ip}:{port}/metrics", timeout=1.5).read().decode()
    except Exception:
        return None
    out = {}
    for n in names:
        vals = [float(m.group(1)) for m in re.finditer(rf'^{re.escape(n)}(?:\{{[^}}]*\}})?\s+(\S+)', txt, re.M)]
        out[n] = sum(vals) if vals else 0.0
    return out


class Run:
    def __init__(self, a):
        self.a, self.cfg = a, POOLS[a.pool]
        self.t0 = time.monotonic()
        self.dir = pathlib.Path(a.out_dir) / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{self.cfg['pool']}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.files = {k: (self.dir / f"{k}.jsonl").open("w") for k in ("log", "requests", "samples")}
        self.lock = threading.Lock()
        self.phase, self.stop_sampler = "idle", False
        self.pods = {}            # name -> dict(created, ready_at, served_at, ip, deleted_at)
        self.desired = None
        self.samples = []
        self.reqs = []

    def rel(self):
        return round(time.monotonic() - self.t0, 2)

    def write(self, kind, rec):
        rec = {"t": ts(), "rel_s": self.rel(), **rec}
        with self.lock:
            self.files[kind].write(json.dumps(rec) + "\n"); self.files[kind].flush()
        return rec

    def event(self, ev, **kw):
        r = self.write("log", {"event": ev, "phase": self.phase, **kw})
        print(f'{r["t"][11:23]} +{r["rel_s"]:>7.2f}s  {ev:<22} {json.dumps(kw)}', flush=True)

    # ---- sampler (thread) -------------------------------------------------------------------
    def sampler(self):
        c = self.cfg
        sel = "app.kubernetes.io/name=" + ("vllm-sim" if self.a.pool == "sim" else "llamacpp")
        first = True
        while not self.stop_sampler:
            t_loop = time.monotonic()
            dep = kubectl_json("get", "deploy", c["deploy"])
            hpa = kubectl_json("get", "hpa", f"keda-hpa-{c['so']}")
            pods = kubectl_json("get", "pods", "-l", sel)
            if not (dep and pods):
                time.sleep(1); continue
            spec, ready = dep["spec"].get("replicas"), dep["status"].get("readyReplicas", 0)
            desired = hpa["status"].get("desiredReplicas") if hpa else None
            if desired != self.desired:
                if self.desired is not None or not first:
                    self.event("hpa_desired_change", old=self.desired, new=desired,
                               hpa_metric=(hpa or {}).get("status", {}).get("currentMetrics"))
                self.desired = desired
            live, q_total, per_pod = set(), 0.0, {}
            for p in pods["items"]:
                name = p["metadata"]["name"]
                if p["metadata"].get("deletionTimestamp"):
                    continue
                live.add(name)
                ip = p["status"].get("podIP")
                is_ready = any(x["type"] == "Ready" and x["status"] == "True" for x in p["status"].get("conditions", []))
                st = self.pods.get(name)
                if st is None:
                    st = self.pods[name] = {"created": p["metadata"]["creationTimestamp"], "ready_at": None,
                                            "served_at": None, "preexisting": first}
                    if not first:
                        self.event("pod_created", pod=name, created=st["created"])
                if is_ready and st["ready_at"] is None:
                    st["ready_at"] = self.rel()
                    if not st["preexisting"]:
                        self.event("pod_ready", pod=name)
                m = scrape(ip, c["port"], c["queue"] + c["served"]) if ip else None
                if m:
                    q = m[c["queue"][0]] + m[c["queue"][1]]
                    q_total += q
                    per_pod[name] = q
                    if st["served_at"] is None and not st["preexisting"] and (m[c["served"][0]] > 0 or m[c["served"][1]] > 0):
                        st["served_at"] = self.rel()
                        self.event("pod_first_served", pod=name)
            for name, st in self.pods.items():
                if name not in live and not st.get("deleted_at"):
                    st["deleted_at"] = self.rel()
                    self.event("pod_gone", pod=name)
            s = self.write("samples", {"phase": self.phase, "spec": spec, "ready": ready, "hpa_desired": desired,
                                       "queue": q_total, "per_pod_queue": per_pod})
            self.samples.append(s)
            first = False
            time.sleep(max(0.0, 1.0 - (time.monotonic() - t_loop)))

    # ---- load ---------------------------------------------------------------------------------
    async def worker(self, i, until):
        async with httpx.AsyncClient(headers=self.cfg["headers"], timeout=httpx.Timeout(300, connect=10)) as cl:
            await asyncio.sleep(i * self.a.stagger)
            n = 0
            while time.monotonic() < until:
                n += 1
                prompt = f"[{i}-{n}-{time.time_ns()}] Write a short story about a lighthouse keeper."
                t_send = self.rel(); wall = ts()
                rec = {"worker": i, "send_rel_s": t_send, "send_t": wall}
                try:
                    r = await stream_chat(cl, GW, prompt, self.a.max_tokens, model=MODEL)
                    rec.update(ok=True, ttft_ms=r["ttft_ms"], total_ms=r["total_ms"], tokens=r["content_chunks"],
                               finish_reason=r["finish_reason"])
                except Exception as e:
                    rec.update(ok=False, error=f"{type(e).__name__}: {e}"[:200])
                    await asyncio.sleep(0.5)
                self.reqs.append(rec)
                self.write("requests", rec)

    async def main(self):
        a, c = self.a, self.cfg
        th = threading.Thread(target=self.sampler, daemon=True); th.start()
        self.event("run_start", pool=c["pool"], deploy=c["deploy"], concurrency=a.concurrency,
                   max_tokens=a.max_tokens, idle=a.idle, high=a.high)
        await asyncio.sleep(a.idle)
        self.phase = "high"
        self.event("load_start")
        until = time.monotonic() + a.high
        await asyncio.gather(*(self.worker(i, until) for i in range(a.concurrency)))
        self.phase = "idle2"
        self.event("load_stop")
        t_stop = time.monotonic(); settled_since = None
        while time.monotonic() - t_stop < a.tail:
            s = self.samples[-1] if self.samples else {}
            if s.get("spec") == a.settle_replicas and s.get("ready") == a.settle_replicas:
                settled_since = settled_since or time.monotonic()
                if time.monotonic() - settled_since > 20:
                    break
            else:
                settled_since = None
            await asyncio.sleep(1)
        self.event("run_end", settled=settled_since is not None)
        self.stop_sampler = True; th.join(timeout=15)
        self.collect()
        self.summary()

    def collect(self):
        c = self.cfg
        ev = subprocess.run(["kubectl", "-n", NS, "get", "events", "--field-selector",
                             f"involvedObject.name=keda-hpa-{c['so']}", "--sort-by=.lastTimestamp", "-o",
                             "custom-columns=FIRST:.firstTimestamp,LAST:.lastTimestamp,COUNT:.count,REASON:.reason,MSG:.message"],
                            capture_output=True, text=True).stdout
        (self.dir / "hpa-events.txt").write_text(ev)
        logs = subprocess.run(["kubectl", "-n", "keda", "logs", "deploy/keda-operator", "--since=15m"],
                              capture_output=True, text=True).stdout
        (self.dir / "keda.log").write_text("\n".join(l for l in logs.splitlines() if c["so"] in l) + "\n")
        dep_ev = subprocess.run(["kubectl", "-n", NS, "get", "events", "--field-selector",
                                 f"involvedObject.name={c['deploy']}", "--sort-by=.lastTimestamp", "-o",
                                 "custom-columns=LAST:.lastTimestamp,REASON:.reason,MSG:.message"],
                                capture_output=True, text=True).stdout
        (self.dir / "deploy-events.txt").write_text(dep_ev)

    def summary(self):
        def pct(xs, p):
            if not xs: return None
            xs = sorted(xs); k = (len(xs) - 1) * p / 100; f = int(k)
            return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)
        f = lambda v, d=0: "-" if v is None else f"{v:,.{d}f}"
        step = self.a.step
        end = self.samples[-1]["rel_s"] if self.samples else 0
        lines = [f"# loadgen {self.cfg['pool']}" + (" (SIMULATED backend)" if self.a.pool == "sim" else ""), "",
                 f"`{' '.join(sys.argv)}`  started {self.samples[0]['t'] if self.samples else '-'}", "",
                 f"| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |",
                 "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        b = 0.0
        while b <= end:
            ss = [s for s in self.samples if b <= s["rel_s"] < b + step]
            rr = [r for r in self.reqs if b <= r["send_rel_s"] < b + step]
            tt = [r["ttft_ms"] for r in rr if r.get("ok") and r.get("ttft_ms") is not None]
            if ss:
                lines.append(f"| {b:.0f} | {ss[-1]['phase']} | {ss[-1]['spec']} | {ss[-1]['ready']} | {ss[-1]['hpa_desired']} | "
                             f"{f(max(s['queue'] for s in ss))} | {len(rr)} | {sum(not r.get('ok') for r in rr)} | "
                             f"{f(pct(tt, 50))} | {f(pct(tt, 95))} |")
            b += step
        ok = [r for r in self.reqs if r.get("ok")]
        lines += ["", f"requests: {len(self.reqs)} sent, {len(ok)} ok, {len(self.reqs) - len(ok)} errors",
                  "", "events:", ""]
        lines += ["    " + l.rstrip() for l in (self.dir / "log.jsonl").read_text().splitlines()]
        (self.dir / "summary.md").write_text("\n".join(lines) + "\n")
        print("\n".join(lines[:len(lines)]))
        print(f"\nwrote {self.dir}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pool", choices=POOLS, required=True, help="sim -> sim-pool (default route), cpu -> llamacpp-pool")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--max-tokens", type=int, default=96)
    p.add_argument("--idle", type=float, default=30)
    p.add_argument("--high", type=float, default=150)
    p.add_argument("--tail", type=float, default=300, help="max s of idle after the load")
    p.add_argument("--settle-replicas", type=int, default=1, help="idle2 ends when spec=ready=this for 20 s")
    p.add_argument("--stagger", type=float, default=0.25)
    p.add_argument("--step", type=float, default=10, help="summary table bucket, s")
    p.add_argument("--out-dir", default="autoscaling/results")
    a = p.parse_args()
    asyncio.run(Run(a).main())


if __name__ == "__main__":
    main()
