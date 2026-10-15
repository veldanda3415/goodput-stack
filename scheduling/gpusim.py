#!/usr/bin/env python3
"""Create / delete / guard the k3d `gpusim` cluster (SIMULATED GPU nodes).

Podman: rootless user socket (the rootful socket was not reachable from this account,
see scenarios/README note). Never touches the default kubeconfig or the k3s cluster.

  gpusim.py up | down | status | guard
"""
import os, subprocess, sys

CLUSTER = "gpusim"
CONTEXT = "k3d-gpusim"
KUBECONFIG = os.path.expanduser("~/.kube/gpusim.yaml")
IMAGE = "rancher/k3s:v1.36.2-k3s1"
SOCK = f"/run/user/{os.getuid()}/podman/podman.sock"
ENV = {**os.environ, "DOCKER_HOST": f"unix://{SOCK}", "DOCKER_SOCK": SOCK}

# agent index -> (role, labels, taint). Labels are set by the kubelet at join.
NODES = {
    0: ("gpu", {"gpu-pool": "t4", "topology.goodput/block": "block-a", "topology.goodput/rack": "rack-1"}),
    1: ("gpu", {"gpu-pool": "t4", "topology.goodput/block": "block-a", "topology.goodput/rack": "rack-2"}),
    2: ("cpu", {"gpu-pool": "none"}),
}


def run(*a, check=True, **kw):
    return subprocess.run(a, env=ENV, check=check, text=True, **kw)


def kubectl(*a, **kw):
    return run("kubectl", "--kubeconfig", KUBECONFIG, "--context", CONTEXT, *a, **kw)


def guard():
    """Refuse to continue unless the kubeconfig points at the k3d gpusim cluster."""
    if not os.path.exists(KUBECONFIG):
        sys.exit(f"refusing: {KUBECONFIG} missing (make gpusim-up)")
    ctx = subprocess.run(["kubectl", "--kubeconfig", KUBECONFIG, "config", "current-context"],
                         capture_output=True, text=True).stdout.strip()
    if ctx != CONTEXT:
        sys.exit(f"refusing: context is {ctx!r}, expected {CONTEXT!r}")


def up():
    have = run("k3d", "cluster", "list", "-o", "json", capture_output=True).stdout
    if f'"name": "{CLUSTER}"' not in have.replace('"name":"', '"name": "'):
        args = ["k3d", "cluster", "create", CLUSTER, "--image", IMAGE, "--servers", "1", "--agents", "3",
                "--kubeconfig-update-default=false", "--kubeconfig-switch-context=false",
                "--k3s-arg", "--disable=traefik@server:0", "--wait"]
        for i, (_, labels) in NODES.items():
            for k, v in labels.items():
                args += ["--k3s-node-label", f"{k}={v}@agent:{i}"]
        run(*args)
    with open(KUBECONFIG, "w") as f:
        run("k3d", "kubeconfig", "get", CLUSTER, stdout=f)
    os.chmod(KUBECONFIG, 0o600)
    guard()
    kubectl("wait", "--for=condition=Ready", "node", "--all", "--timeout=180s")
    for n in subprocess.run(["kubectl", "--kubeconfig", KUBECONFIG, "get", "nodes", "-l", "gpu-pool=t4", "-o", "name"],
                            capture_output=True, text=True).stdout.split():
        kubectl("taint", "node", n.split("/")[-1], "nvidia.com/gpu=present:NoSchedule", "--overwrite")
    kubectl("get", "nodes", "-L", "gpu-pool,topology.goodput/block,topology.goodput/rack")


def down():
    run("k3d", "cluster", "delete", CLUSTER)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"up": up, "down": down, "guard": guard,
     "status": lambda: (guard(), kubectl("get", "nodes", "-o", "wide"))}.get(cmd, lambda: sys.exit(__doc__))()
