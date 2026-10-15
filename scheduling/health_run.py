#!/usr/bin/env python3
"""Scenario 04 driver (SIMULATED GPU fault): injects the GPUXidError node condition, measures phases, remediates.
Usage: health_run.py [runs]. Starts health_controller.py itself. Prints a JSON result per run."""
import datetime, json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpusim  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
COND = "GPUXidError"


def kc(*a, inp=None, check=True):
    return subprocess.run(["kubectl", "--kubeconfig", gpusim.KUBECONFIG, "--context", gpusim.CONTEXT, *a],
                          input=inp, capture_output=True, text=True, check=check).stdout


def js(*a):
    return json.loads(kc(*a, "-o", "json"))


def set_cond(node, status):
    body = {"status": {"conditions": [{"type": COND, "status": status, "reason": "XID79" if status == "True" else "Recovered",
            "message": "SIMULATED: Xid 79 GPU has fallen off the bus" if status == "True" else "SIMULATED: cleared",
            "lastHeartbeatTime": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lastTransitionTime": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}]}}
    kc("patch", "node", node, "--subresource=status", "--type=strategic", "-p", json.dumps(body))


def dep_pods():
    return [p for p in js("get", "pods", "-l", "app=gpu-sim")["items"]]


def ready(p):
    return any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"].get("conditions", []))


def wait(cond, timeout, what):
    t = time.time()
    while time.time() - t < timeout:
        r = cond()
        if r:
            return r
        time.sleep(0.2)
    raise SystemExit(f"timeout waiting for {what}")


def setup():
    kc("-n", "team-a", "delete", "job", "--all", "--ignore-not-found", check=False)
    kc("-n", "default", "scale", "deploy/gpu-sim", "--replicas=1")
    pod = wait(lambda: next((p for p in dep_pods() if ready(p)), None), 120, "deployment pod")
    node = pod["spec"]["nodeName"]
    job = subprocess.run([sys.executable, os.path.join(HERE, "kjob.py"), "health-job", "team-a", "--gpus", "1",
                          "--prefer-node", node, "--backoff", "3"], capture_output=True, text=True, check=True).stdout
    kc("apply", "-f", "-", inp=job)
    wait(lambda: [p for p in js("-n", "team-a", "get", "pods")["items"] if p["status"].get("phase") == "Running"], 120, "job pod")
    return node


def one_run(i, node, ctl):
    jpod = js("-n", "team-a", "get", "pods")["items"]
    before = {"deploy": [p["metadata"]["name"] + "@" + p["spec"]["nodeName"] for p in dep_pods()],
              "job": [p["metadata"]["name"] + "@" + p["spec"].get("nodeName", "?") for p in jpod]}
    old = {p["metadata"]["name"] for p in dep_pods()}
    t0 = time.time()
    set_cond(node, "True")
    t_taint = wait(lambda: any(t["key"] == "nvidia.com/gpu-unhealthy" for t in js("get", "node", node)["spec"].get("taints", [])) and time.time(), 30, "taint")
    t_evict = wait(lambda: not (old & {p["metadata"]["name"] for p in dep_pods() if not p["metadata"].get("deletionTimestamp")}) and time.time(), 60, "evict")
    def new_ready():
        n = [p for p in dep_pods() if p["metadata"]["name"] not in old and ready(p) and not p["metadata"].get("deletionTimestamp")]
        return n[0] if n else None
    newp = wait(new_ready, 120, "reschedule")
    t_ready = time.time()
    wl = js("-n", "team-a", "get", "workload")["items"][0]
    conds = [(c["type"], c["status"], c.get("reason")) for c in wl["status"].get("conditions", [])]
    job_state = [p["metadata"]["name"] + "@" + p["spec"].get("nodeName", "?") + ":" + p["status"].get("phase", "") for p in js("-n", "team-a", "get", "pods")["items"]]
    t_rem = time.time()
    set_cond(node, "False")
    wait(lambda: (lambda sp: not sp.get("unschedulable") and not any(t["key"] == "nvidia.com/gpu-unhealthy" for t in sp.get("taints", [])))(js("get", "node", node)["spec"]), 30, "uncordon")
    t_back = time.time()
    return {"run": i, "SIMULATED": True, "node": node, "before": before, "after_deploy_pod": newp["metadata"]["name"] + "@" + newp["spec"]["nodeName"],
            "job_pods_after": job_state, "workload_conditions": conds,
            "signal_to_taint_s": round(t_taint - t0, 2), "taint_to_deploy_pod_gone_s": round(t_evict - t_taint, 2),
            "evicted_to_new_pod_ready_s": round(t_ready - t_evict, 2), "signal_to_ready_total_s": round(t_ready - t0, 2),
            "clear_to_uncordoned_s": round(t_back - t_rem, 2)}


def main():
    gpusim.guard()
    for n in js("get", "nodes", "-l", "gpu-pool=t4")["items"]:
        assert not n["spec"].get("unschedulable"), f"{n['metadata']['name']} is cordoned; clean up first"
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    ctl = open("/tmp/health_controller.log", "w")
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "health_controller.py")], stdout=ctl, stderr=subprocess.STDOUT)
    try:
        time.sleep(2)
        node = setup()
        for i in range(1, runs + 1):
            print(json.dumps(one_run(i, node, proc)), flush=True)
            # next run: wait for steady state; target whichever node now hosts the deployment pod
            node = wait(lambda: next((p["spec"]["nodeName"] for p in dep_pods() if ready(p)), None), 60, "steady")
            time.sleep(15)
    finally:
        proc.terminate()
        ctl.close()
        kc("-n", "team-a", "delete", "job", "health-job", "--ignore-not-found", check=False)
        kc("-n", "default", "scale", "deploy/gpu-sim", "--replicas=0", check=False)


if __name__ == "__main__":
    main()
