#!/usr/bin/env python3
"""GPU node health controller for the SIMULATED gpusim cluster (scenario 04).

Watches t4 nodes for a node condition (default GPUXidError=True, the kind of condition a Node Problem
Detector custom plugin / DCGM-based checker would publish for an XID error). When it appears:
  fence : cordon, annotate ownership, requeue Kueue workloads, taint nvidia.com/gpu-unhealthy=xid NoSchedule + NoExecute
  drain : NoExecute makes the taint manager evict pods; Kueue-managed Jobs with a pod on the node get their
          Workload deactivated and re-activated, so Kueue evicts and requeues the WHOLE workload
When the condition goes False / disappears: remove taints, uncordon (only nodes this controller fenced).
Every action is a JSON line on stdout with a wall-clock timestamp. Refuses to run unless the context is k3d-gpusim.
"""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpusim  # noqa: E402  (guard(), KUBECONFIG, CONTEXT)

COND = os.environ.get("HEALTH_CONDITION", "GPUXidError")
TAINT = "nvidia.com/gpu-unhealthy"
OWNER = "goodput/fenced-by"


def log(**kw):
    print(json.dumps({"ts": round(time.time(), 3), **kw}), flush=True)


def kc(*a, check=True):
    return subprocess.run(["kubectl", "--kubeconfig", gpusim.KUBECONFIG, "--context", gpusim.CONTEXT, *a],
                          capture_output=True, text=True, check=check)


def unhealthy(node):
    return any(c["type"] == COND and c["status"] == "True" for c in node["status"].get("conditions", []))


def requeue_kueue_workloads(node):
    pods = json.loads(kc("get", "pods", "-A", "-o", "json", "--field-selector", f"spec.nodeName={node}").stdout)["items"]
    seen = set()
    for p in pods:
        ns = p["metadata"]["namespace"]
        owner = next((o for o in p["metadata"].get("ownerReferences", []) if o["kind"] == "Job"), None)
        if not owner or (ns, owner["name"]) in seen:
            continue
        job = json.loads(kc("-n", ns, "get", "job", owner["name"], "-o", "json").stdout)
        if "kueue.x-k8s.io/queue-name" not in job["metadata"].get("labels", {}):
            continue
        seen.add((ns, owner["name"]))
        wls = json.loads(kc("-n", ns, "get", "workload", "-o", "json").stdout)["items"]
        wl = next((w for w in wls if any(o["name"] == owner["name"] for o in w["metadata"].get("ownerReferences", []))), None)
        if not wl:
            continue
        name = wl["metadata"]["name"]
        kc("-n", ns, "patch", "workload", name, "--type=merge", "-p", '{"spec":{"active":false}}')
        log(event="workload_deactivated", ns=ns, workload=name, node=node)
        for _ in range(100):
            w = json.loads(kc("-n", ns, "get", "workload", name, "-o", "json").stdout)
            if any(c["type"] == "Evicted" and c["status"] == "True" for c in w["status"].get("conditions", [])):
                break
            time.sleep(0.2)
        kc("-n", ns, "patch", "workload", name, "--type=merge", "-p", '{"spec":{"active":true}}')
        log(event="workload_reactivated", ns=ns, workload=name, node=node)


def fence(node):
    # Order matters: cordon -> requeue Kueue workloads -> NoExecute. If NoExecute goes first, the sim pod exits 0 on
    # SIGTERM, the Job controller counts it Succeeded and the Job is marked Complete instead of requeued (observed).
    kc("cordon", node)
    kc("annotate", "node", node, f"{OWNER}=health-controller", "--overwrite")
    log(event="cordoned", node=node)
    requeue_kueue_workloads(node)
    kc("taint", "node", node, f"{TAINT}=xid:NoSchedule", f"{TAINT}=xid:NoExecute", "--overwrite")
    log(event="tainted", node=node)


def unfence(node):
    kc("taint", "node", node, f"{TAINT}-", check=False)
    log(event="untainted", node=node)
    kc("uncordon", node)
    kc("annotate", "node", node, f"{OWNER}-")
    log(event="uncordoned", node=node)


def handle(node):
    name = node["metadata"]["name"]
    node = json.loads(kc("get", "node", name, "-o", "json").stdout)  # queued watch events can be stale
    fenced = node["metadata"].get("annotations", {}).get(OWNER) == "health-controller"
    if unhealthy(node) and not fenced:
        log(event="signal_seen", node=name, condition=COND)
        fence(name)
    elif not unhealthy(node) and fenced:
        log(event="signal_cleared", node=name)
        unfence(name)


def main():
    gpusim.guard()
    log(event="start", condition=COND)
    while True:
        proc = subprocess.Popen(["kubectl", "--kubeconfig", gpusim.KUBECONFIG, "--context", gpusim.CONTEXT, "get", "nodes",
                                 "-l", "gpu-pool=t4", "--watch", "--output-watch-events", "-o", "json"],
                                stdout=subprocess.PIPE, text=True)
        dec, buf = json.JSONDecoder(), ""
        for line in proc.stdout:
            buf += line
            try:
                ev, end = dec.raw_decode(buf)
            except json.JSONDecodeError:
                continue
            buf = buf[end:].lstrip()
            if ev.get("type") in ("ADDED", "MODIFIED"):
                handle(ev["object"])
        log(event="watch_restarted")


if __name__ == "__main__":
    main()
