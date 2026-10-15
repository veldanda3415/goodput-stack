# scheduling/

GPU scheduling experiments on **SIMULATED GPUs**: a k3d cluster (`gpusim`) whose "GPU nodes" advertise fake
`nvidia.com/gpu` devices. Workload pods are the llm-d inference simulator (no GPU, no model). Everything here exercises
the Kubernetes scheduling mechanics; none of it measures real GPU behaviour. The k3s daily cluster is never used:
all tooling pins `~/.kube/gpusim.yaml` / context `k3d-gpusim` and refuses otherwise (`gpusim.py guard`).

## Installed (pinned)
| Component | Version | Source |
|---|---|---|
| k3d | v5.9.0 (rootless Podman; needs `DOCKER_HOST` + `DOCKER_SOCK`, and cpuset cgroup delegation) | `k3d version` |
| k3s node image | `rancher/k3s:v1.36.2-k3s1` (k3s v1.36.2+k3s1) | `scheduling/gpusim.py` |
| Run:ai fake-gpu-operator | chart 0.2.1 (OCI digest `sha256:e73fc8c0…c11`) | `oci://ghcr.io/run-ai/fake-gpu-operator/fake-gpu-operator`; values `fake-gpu-operator*.values.yaml` |
| Kueue | chart 0.20.1 (app v0.20.1; digest `sha256:909f655f…987`), API `kueue.x-k8s.io/v1beta2` | `oci://registry.k8s.io/kueue/charts/kueue`; 0.20.2 existed but was pinned 0.20.1 as first checked |
| Workload image | `ghcr.io/llm-d/llm-d-inference-sim:v0.10.2` (`sha256:86e9d502…f27f`) | `deploy/charts/inference/values.yaml` |

Cluster: 1 server + 3 agents. agent-0/1 = pool `t4` (label `gpu-pool=t4`, taint `nvidia.com/gpu=present:NoSchedule`,
`topology.goodput/block=block-a`, racks `rack-1`/`rack-2`, 2 simulated Tesla-T4 each); agent-2 = CPU only.
Kueue is currently deployed WITH `waitForPodsReady` (`kueue.waitforpods.values.yaml`: 60 s timeout, backoff 10 s, limit 1).

## make targets
`make gpusim-up` / `gpusim-down` / `gpusim-status` · `make gpusim-operator MODE=deviceplugin|dra` ·
`make gpusim-kueue [ARGS=waitforpods]` · `make gpusim-health` (controller) · `make gpusim-health-run RUNS=3` (scenario 04 driver).
Other scripts: `kjob.py` (prints a Kueue Job), `manifests/` (Deployment, DRA claims, queues, TAS).

## Scenarios
| # | Outcome (one line) |
|---|---|
| [01 GPU exhaustion](scenarios/01-gpu-exhaustion.md) | 4 of 5 GPU pods Running on 2×2 fake GPUs; 5th Pending `Insufficient nvidia.com/gpu`; taint-mismatch and quota blocks give different messages; fake DCGM exports only 3 metrics |
| [02 Sharing and DRA](scenarios/02-sharing-and-dra.md) | time-slicing replicas NOT supported by the legacy plugin in the pinned operator (documented, not faked); DRA works via the operator's DRA plugin: template claim, shared claim, ResourceSlices |
| [03 Kueue](scenarios/03-kueue-quota-preemption.md) | over-quota stays suspended, borrowing, cohort reclaim + priority preemption, gang behaviour with/without `waitForPodsReady`, TAS rack/block placement |
| [04 GPU node health](scenarios/04-gpu-node-health.md) | injected XID-style node condition → cordon, Kueue requeue, NoExecute taint → pods on the other t4 node in 3.8-6.7 s (3 runs) → remediation 0.7 s |

## Honest limits
- GPUs are fake: the operator makes the scheduler believe devices exist. No hardware detection, no GPU memory enforcement,
  no real contention, no NVLink/PCIe/MIG/MPS behaviour, no real XID/ECC faults (condition injected by script).
- DCGM: the fake exporter exposes only `DCGM_FI_DEV_FB_FREE/FB_USED/GPU_UTIL`; no health, XID, ECC or power metrics.
- Time-slicing is not demonstrated (see scenario 02); DRA time-slicing config effects are unverified.
- Timings are single-machine, 3-run, polling-based, with a cached sim image: not benchmarks.
- Node "racks"/"blocks" are labels I set; there is no network locality.
- k3d runs rootless Podman on a shared machine; resource requests are small and unrelated to any real GPU node.
