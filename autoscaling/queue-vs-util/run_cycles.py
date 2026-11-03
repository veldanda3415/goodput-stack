#!/usr/bin/env python3
"""Build 17 Task A: run the queue-depth (KEDA) vs CPU-utilisation (HPA) cycles on llamacpp-pool in a fixed random order.

    .venv/bin/python autoscaling/queue-vs-util/run_cycles.py --seed 17 [--cycles 3] [--only keda:heavy] [--dry-run]

Configs: keda = ScaledObject inf-llamacpp (autoscaling/scaledobject-llamacpp.yaml, unchanged); cpu50 / cpu80 = HPA
inf-llamacpp-cpu (hpa-cpu-{50,80}.yaml). Exactly one autoscaler owns the Deployment: before a cycle the other one is
deleted and `kubectl get hpa` must list exactly one HPA targeting inf-llamacpp.
Profiles: heavy = 6 streams for 150 s, light = 2 streams (= --parallel 2 slots of one pod) for 150 s; --max-tokens 64,
--idle 20, --tail 300, as in the 2026-10-14 cycle: one prompt template, a unique "[worker-n-time_ns]" prefix per
request. (--prompts fixed sends the same prompt sequence every cycle; on llamacpp-pool the EPP prefix-cache-scorer
then pins those prompts to the one long-lived pod across cycles: see results/queue_vs_util.md. Not used for results.)
Before every cycle: deployment at spec = ready = 1 and the pool idle (queue 0 on every pod) for 60 s in a row.
Writes autoscaling/results/queue-vs-util/order.jsonl (one row per cycle: config, profile, start conditions, run dir).

--pool sim (secondary, SIMULATED): sim-pool, configs keda (scaledobject-vllm-sim.yaml, paused-replicas annotation removed)
and cpu50 (hpa-sim-cpu-50.yaml), heavy = 8 streams, --max-tokens 96 (the 2026-10-14 sim cycle);
output autoscaling/results/queue-vs-util-sim/.
"""
import argparse, json, pathlib, random, subprocess, sys, time, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "autoscaling"))
from loadgen import NS, kubectl_json, node_cpu, pod_cpu_usec, scrape, ts  # noqa: E402

POOLS = {   # --pool: cpu = llamacpp-pool (primary, real CPU (laptop)); sim = sim-pool (secondary, SIMULATED)
    "cpu": dict(deploy="inf-llamacpp", so="inf-llamacpp", cpu_hpa="inf-llamacpp-cpu", label="llamacpp", port=8080,
                so_file=REPO / "autoscaling" / "scaledobject-llamacpp.yaml", hpa_file="hpa-cpu-{t}.yaml",
                queue=("llamacpp:requests_processing", "llamacpp:requests_deferred"),
                profiles={"heavy": 6, "light": 2}, max_tokens=64, configs=("keda", "cpu50", "cpu80"),
                out=REPO / "autoscaling" / "results" / "queue-vs-util"),
    "sim": dict(deploy="inf-vllm-sim", so="inf-vllm-sim", cpu_hpa="inf-vllm-sim-cpu", label="vllm-sim", port=8000,
                so_file=REPO / "autoscaling" / "scaledobject-vllm-sim.yaml", hpa_file="hpa-sim-cpu-{t}.yaml",
                queue=("vllm:num_requests_running", "vllm:num_requests_waiting"),
                profiles={"heavy": 8}, max_tokens=96, configs=("keda", "cpu50"),
                out=REPO / "autoscaling" / "results" / "queue-vs-util-sim"),
}
P = POOLS["cpu"]


def kc(*a, check=True):
    r = subprocess.run(["kubectl", "-n", NS, *a], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"kubectl {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout.strip()


def hpas_on_deploy():
    d = kubectl_json("get", "hpa") or {"items": []}
    return [h["metadata"]["name"] for h in d["items"] if h["spec"]["scaleTargetRef"]["name"] == P["deploy"]]


def wait(cond, what, timeout=180):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        if cond():
            return
        time.sleep(2)
    raise RuntimeError(f"timeout waiting for {what}")


def set_config(cfg):
    """Make `cfg` the only autoscaler of inf-llamacpp."""
    if cfg == "keda":
        kc("delete", "hpa", P["cpu_hpa"], "--ignore-not-found")
        wait(lambda: P["cpu_hpa"] not in hpas_on_deploy(), "cpu HPA gone")
        kc("apply", "-f", str(P["so_file"]))
        kc("annotate", "scaledobject", P["so"], "autoscaling.keda.sh/paused-replicas-")   # sim-pool was left paused at 2
        wait(lambda: hpas_on_deploy() == ["keda-hpa-" + P["so"]], "KEDA HPA only")
    else:
        kc("delete", "scaledobject", P["so"], "--ignore-not-found")
        kc("delete", "hpa", P["cpu_hpa"], "--ignore-not-found")    # fresh HPA per cycle: no carried-over recommendations
        wait(lambda: not hpas_on_deploy(), "no HPA on the deployment")
        kc("apply", "-f", str(HERE / P["hpa_file"].format(t=cfg[3:])))
        wait(lambda: hpas_on_deploy() == [P["cpu_hpa"]], "CPU HPA only")
    return {"hpas_on_deploy": hpas_on_deploy(), "hpa_list": kc("get", "hpa", "--no-headers")}


def pool_state():
    dep = kubectl_json("get", "deploy", P["deploy"])
    pods = kubectl_json("get", "pods", "-l", "app.kubernetes.io/name=" + P["label"])["items"]
    q = 0.0
    for p in pods:
        ip = p["status"].get("podIP")
        m = scrape(ip, P["port"], P["queue"]) if ip else None
        q += sum(m.values()) if m else 0
    return dep["spec"].get("replicas"), dep["status"].get("readyReplicas", 0), len(pods), q, pods


def wait_idle(hold=60, timeout=900):
    """spec = ready = 1 pod and queue 0 for `hold` s in a row; returns the start conditions."""
    t0, since = time.monotonic(), None
    while time.monotonic() - t0 < timeout:
        spec, ready, npods, q, pods = pool_state()
        ok = spec == 1 and ready == 1 and npods == 1 and q == 0
        since = (since or time.monotonic()) if ok else None
        if since and time.monotonic() - since >= hold:
            uid = pods[0]["metadata"]["uid"]
            c0, n0, t_a = pod_cpu_usec(uid), node_cpu(), time.monotonic()
            time.sleep(5)
            c1, n1, t_b = pod_cpu_usec(uid), node_cpu(), time.monotonic()
            return {"waited_s": round(time.monotonic() - t0, 1), "idle_hold_s": hold, "spec": spec, "ready": ready,
                    "pod": pods[0]["metadata"]["name"], "queue": q,
                    "pod_cpu_cores_5s": round((c1 - c0) / 1e6 / (t_b - t_a), 3) if c0 is not None else None,
                    "node_cpu_busy_5s": round((n1[0] - n0[0]) / (n1[1] - n0[1]), 4)}
        time.sleep(2)
    raise RuntimeError("pool did not return to 1 idle replica")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--only", help="config:profile, one cycle (smoke test)")
    ap.add_argument("--start-at", type=int, default=0, help="resume at this index of the planned order")
    ap.add_argument("--prom", required=True, help="Prometheus base URL reachable from this host")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pool", choices=POOLS, default="cpu")
    ap.add_argument("--prompts", choices=("unique", "fixed"), default="unique")
    a = ap.parse_args()
    global P
    P = POOLS[a.pool]
    OUT, PROFILES, CONFIGS = P["out"], P["profiles"], P["configs"]
    if a.only:
        plan = [tuple(a.only.split(":"))]
    else:
        plan = [(c, p) for c in CONFIGS for p in PROFILES for _ in range(a.cycles)]
        random.Random(a.seed).shuffle(plan)
    OUT.mkdir(parents=True, exist_ok=True)
    print("plan:", plan, flush=True)
    if a.dry_run:
        return
    for i, (cfg, prof) in enumerate(plan):
        if i < a.start_at:
            continue
        row = {"index": i, "seed": a.seed, "config": cfg, "profile": prof, "t_config": ts()}
        row["autoscaler"] = set_config(cfg)
        row["start"] = wait_idle()
        row["t_load_cmd"] = ts()
        cmd = [sys.executable, str(REPO / "autoscaling" / "loadgen.py"), "--pool", a.pool, "--concurrency", str(PROFILES[prof]),
               "--max-tokens", str(P["max_tokens"]), "--idle", "20", "--high", "150", "--tail", "300",
               "--out-dir", str(OUT / "runs"), "--prom", a.prom] + (["--fixed-prompts"] if a.prompts == "fixed" else []) + (["--hpa", P["cpu_hpa"]] if cfg != "keda" else [])
        row["cmd"] = " ".join(cmd[1:])
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        row["rc"] = r.returncode
        row["run_dir"] = next((l.split("wrote ", 1)[1].strip() for l in r.stdout.splitlines() if l.startswith("wrote ")), None)
        if r.returncode:
            row["stderr_tail"] = r.stderr[-2000:]
        row["t_end"] = ts()
        with (OUT / "order.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps({k: row[k] for k in ("index", "config", "profile", "rc", "run_dir")}), flush=True)


if __name__ == "__main__":
    main()
