"""In-cluster engine target: an existing Deployment + Service (the vLLM simulator), driven
directly via its ClusterIP from the k3s host. No process is spawned, no port-forward tunnel.

Per point (K8sServer):
  1. if the point's simulator config (ConfigMap + `server.sim` overrides) differs from what
     is live, patch the ConfigMap
  2. roll the Deployment (`restart_per_point`, or whenever the config changed) and wait until
     only the new pods are left and the Service answers /health/ready
  3. hand `base_url` to the load client; afterwards save the pods' logs
Per experiment (Session): remember the ConfigMap as found and restore it at the end, so a
benchmark never leaves the Helm release in a different state. Helm 4 applies server-side, so the
patch is made under our own field manager and that manager's ownership is dropped on restore -
otherwise the next `helm upgrade` fails with a field conflict on .data.

Reaching the ClusterIP from the host works because the host IS the (single) k3s node and
kube-router lets node traffic through the NetworkPolicy. Elsewhere (k3d, remote cluster) set
`server.base_url` to a port-forward instead.
"""

from __future__ import annotations

import gzip
import json
import platform
import re
import subprocess
import time
from pathlib import Path

import httpx
import yaml


def kubectl(*args: str, ns: str | None = None, parse: bool = False, check: bool = True):
    cmd = ["kubectl", *(["-n", ns] if ns else []), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {r.stderr.strip()[:500]}")
    return json.loads(r.stdout) if parse and r.stdout else r.stdout


FIELD_MANAGER = "goodput-bench"


def release_fields(ns: str, kind: str, name: str, manager: str = FIELD_MANAGER) -> None:
    """Forget `manager`'s field ownership so Helm's server-side apply owns the object alone again."""
    obj = kubectl("get", kind, name, "-o", "json", "--show-managed-fields", ns=ns, parse=True)
    fields = obj["metadata"].get("managedFields") or []
    keep = [f for f in fields if f.get("manager") != manager]
    if len(keep) != len(fields):
        patch = json.dumps({"metadata": {"managedFields": keep or [{}]}})
        kubectl("patch", kind, name, "--type", "merge", "-p", patch, ns=ns)


def _selector(deploy: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in deploy["spec"]["selector"]["matchLabels"].items())


class Session:
    """One experiment against one Deployment: tracks and restores the simulator ConfigMap."""

    def __init__(self, cfg: dict):
        self.s = cfg["server"]
        self.ns = self.s["namespace"]
        self.original: dict | None = None   # parsed config as found (None = no ConfigMap managed)
        self.live: dict | None = None
        if self.s.get("configmap"):
            self.original = self.read_config()
            self.live = dict(self.original)

    def read_config(self) -> dict:
        cm = kubectl("get", "configmap", self.s["configmap"], "-o", "json", ns=self.ns, parse=True)
        return yaml.safe_load(cm["data"][self.s["config_key"]]) or {}

    def write_config(self, config: dict) -> None:
        data = yaml.safe_dump(config, sort_keys=True)
        patch = json.dumps({"data": {self.s["config_key"]: data}})
        kubectl("patch", "configmap", self.s["configmap"], "--type", "merge", "-p", patch,
                f"--field-manager={FIELD_MANAGER}", ns=self.ns)
        self.live = dict(config)

    def desired(self, overrides: dict | None) -> dict | None:
        return None if self.original is None else {**self.original, **(overrides or {})}

    def close(self) -> None:
        """Restore the ConfigMap and roll once more, so the pods match the release again."""
        if self.original is not None and self.live != self.original:
            print("restoring simulator ConfigMap and pods to the release's config", flush=True)
            self.write_config(self.original)
            K8sServer.restart(self.s, startup_timeout_s=self.s["startup_timeout_s"])
        if self.original is not None:
            release_fields(self.ns, "configmap", self.s["configmap"])


class K8sServer:
    """Same interface as LlamaServer (context manager, base_url, memory_info)."""

    def __init__(self, cfg: dict, out_dir: Path, session: Session):
        self.cfg, self.s, self.out_dir, self.session = cfg, cfg["server"], out_dir, session
        self.ns = self.s["namespace"]
        self.base_url = self.s.get("base_url") or self._service_url()
        self.startup_s: float | None = None
        self.pods: list[str] = []
        self.info: dict = {}

    def _service_url(self) -> str:
        svc = kubectl("get", "svc", self.s["service"], "-o", "json", ns=self.ns, parse=True)
        port = svc["spec"]["ports"][0]["port"]
        return f"http://{svc['spec']['clusterIP']}:{port}"

    def __enter__(self) -> "K8sServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        want = self.session.desired(self.s.get("sim"))
        changed = want is not None and want != self.session.live
        if changed:
            self.session.write_config(want)
        t0 = time.monotonic()
        if changed or self.s.get("restart_per_point", True):
            self.restart(self.s, self.s["startup_timeout_s"])
        self._wait_ready(t0)
        self.startup_s = time.monotonic() - t0
        self.info = self._describe(want)
        (self.out_dir / "target.json").write_text(json.dumps(self.info, indent=2) + "\n")

    @staticmethod
    def restart(s: dict, startup_timeout_s: float) -> None:
        """Roll the Deployment and wait until the old pods are GONE (not just terminating),
        so the Service can only route to fresh pods."""
        ns = s["namespace"]
        deploy = kubectl("get", "deploy", s["deployment"], "-o", "json", ns=ns, parse=True)
        sel = _selector(deploy)
        old = kubectl("get", "pods", "-l", sel, "-o", "jsonpath={.items[*].metadata.name}", ns=ns).split()
        kubectl("rollout", "restart", f"deploy/{s['deployment']}", ns=ns)
        kubectl("rollout", "status", f"deploy/{s['deployment']}", f"--timeout={int(startup_timeout_s)}s", ns=ns)
        if old:
            kubectl("wait", "--for=delete", *(f"pod/{p}" for p in old), "--timeout=120s", ns=ns, check=False)

    def _wait_ready(self, t0: float) -> None:
        deadline = t0 + self.s["startup_timeout_s"]
        ok_in_a_row = 0
        with httpx.Client(timeout=2.0) as client:
            while time.monotonic() < deadline:
                try:
                    ok_in_a_row = ok_in_a_row + 1 if client.get(f"{self.base_url}{self.s['health_path']}").status_code == 200 else 0
                except httpx.TransportError:
                    ok_in_a_row = 0
                if ok_in_a_row >= 3:   # a few in a row: NetworkPolicy/endpoint updates have settled
                    return
                time.sleep(0.2)
        raise TimeoutError(f"{self.base_url}{self.s['health_path']} not ready after {self.s['startup_timeout_s']}s")

    def _describe(self, config: dict | None) -> dict:
        deploy = kubectl("get", "deploy", self.s["deployment"], "-o", "json", ns=self.ns, parse=True)
        pods = kubectl("get", "pods", "-l", _selector(deploy), "-o", "json", ns=self.ns, parse=True)["items"]
        live = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
        self.pods = [p["metadata"]["name"] for p in live]
        statuses = [(p.get("status", {}).get("containerStatuses") or [{}])[0] for p in live]
        info = {
            "base_url": self.base_url,
            "pods": self.pods,
            "nodes": sorted({p["spec"].get("nodeName") for p in live}),
            "image": deploy["spec"]["template"]["spec"]["containers"][0]["image"],
            "image_ids": sorted({s.get("imageID") for s in statuses if s.get("imageID")}),
            "config_requested": config,
        }
        if self.pods:
            info["config_effective"] = effective_config(kubectl("logs", self.pods[0], ns=self.ns, check=False))
        return info

    def stop(self) -> None:
        cap = int(self.cfg["storage"]["max_log_mib"] * 1024 * 1024)
        for i, pod in enumerate(self.pods):
            log = kubectl("logs", pod, "--timestamps", ns=self.ns, check=False).encode()
            name = "server.log.gz" if i == 0 else f"server-{pod}.log.gz"
            with gzip.open(self.out_dir / name, "wb") as f:
                f.write(log[:cap])

    def memory_info(self) -> dict:
        # startup_s here = k8s bring-up (roll + wait for old pods to go + Service ready), not a process start
        return {"startup_s": round(self.startup_s or 0, 3), "log_memory_lines": [], "log_truncated_bytes": 0}


def effective_config(log: str) -> dict | None:
    """The simulator prints its whole config as JSON at start ('"Configuration:" =<' ... '>')."""
    m = re.search(r'"Configuration:" =<\n(.*?)\n\s*>\s*\n', log, re.S)
    if not m:
        return None
    try:
        return json.loads("\n".join(line.lstrip("\t") for line in m.group(1).splitlines()))
    except json.JSONDecodeError:
        return None


def collect(cfg: dict) -> dict:
    """Provenance for an in-cluster target (merged into sysinfo.collect)."""
    s = cfg["server"]
    ns = s["namespace"]
    deploy = kubectl("get", "deploy", s["deployment"], "-o", "json", ns=ns, parse=True)
    image = deploy["spec"]["template"]["spec"]["containers"][0]["image"]
    version = kubectl("version", "-o", "json", parse=True, check=False) or {}
    node = kubectl("get", "nodes", "-o", "json", parse=True, check=False) or {}
    helm = {}
    release = deploy["metadata"].get("annotations", {}).get("meta.helm.sh/release-name")
    if release:
        r = subprocess.run(["helm", "list", "-n", ns, "-f", f"^{release}$", "-o", "json"], capture_output=True, text=True)
        rows = json.loads(r.stdout or "[]")
        helm = {k: rows[0].get(k) for k in ("name", "chart", "revision", "app_version")} if rows else {}
    sim_config = Session(cfg).original if s.get("configmap") else None
    tag = image.split("@")[0].rsplit(":", 1)[-1]
    return {
        "engine": f"llm-d-inference-sim {tag} (k8s {ns}/{s['deployment']})",
        "measurement": "SIMULATED (llm-d-inference-sim): latencies are configured, not measured",
        "kube_context": kubectl("config", "current-context", check=False).strip(),
        "kube_server_version": (version.get("serverVersion") or {}).get("gitVersion"),
        "nodes": [n["metadata"]["name"] for n in node.get("items", [])],
        "helm": helm,
        "deployment": s["deployment"],
        "replicas": deploy["spec"].get("replicas"),
        "image": image,
        "sim_config": sim_config,
        "client_host": platform.node(),
    }
