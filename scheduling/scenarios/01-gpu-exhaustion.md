# 01 - GPU exhaustion, taints and quota (SIMULATED GPUs)

> **SIMULATED.** `nvidia.com/gpu` is advertised by run-ai/fake-gpu-operator; nothing is detected
> from hardware. The pods are llm-d-inference-sim (no model, no GPU). What is real here is the
> Kubernetes scheduler/API behaviour, not any GPU behaviour. 2026-10-15, k3d `gpusim`, k3s v1.36.2+k3s1.

## Goal
Show how whole-integer GPUs are advertised, what exhaustion looks like, and tell apart the three
ways a GPU pod fails to start: no capacity, taint mismatch, quota.

## Setup
- fake-gpu-operator **0.2.1** (chart `oci://ghcr.io/run-ai/fake-gpu-operator/fake-gpu-operator`, app 0.2.1,
  digest `sha256:e73fc8c0...6c11`; found via GitHub releases API, values keys from the chart's
  `values.yaml` and README "GPU Topology" at tag v0.2.1). Values: [fake-gpu-operator.values.yaml](../fake-gpu-operator.values.yaml).
- Nodes `k3d-gpusim-agent-0/1` labelled `run.ai/simulated-gpu-node-pool=t4`, pool `t4` = 2 x `Tesla-T4`, 15360 MiB.
  They also carry `gpu-pool=t4` and the taint `nvidia.com/gpu=present:NoSchedule` (set by [gpusim.py](../gpusim.py)).
- Chart override `runtimeClass.enabled=false`: k3s already owns a RuntimeClass `nvidia` (handler `nvidia`);
  the first `helm install` failed with `RuntimeClass "nvidia" ... exists and cannot be imported into the current release`.
- Workload: [gpu-sim-deployment.yaml](../manifests/gpu-sim-deployment.yaml) (`nvidia.com/gpu: 1`, toleration, nodeSelector `gpu-pool=t4`).

## Expected
2 nodes x 2 GPUs = 4 pods run; the 5th is Pending with `Insufficient nvidia.com/gpu`.

## What happened
Node allocatable (`kubectl get node k3d-gpusim-agent-0 -o jsonpath='{.status.allocatable}'`) shows `"nvidia.com/gpu":"2"` on both t4
nodes and nothing on the other two. The operator also added labels such as `nvidia.com/gpu.product=Tesla-T4`, `nvidia.com/gpu.memory=15360`.

`kubectl scale deploy gpu-sim --replicas=5` -> 4 Running (2 per t4 node), 1 Pending. Event
(`kubectl get events --field-selector reason=FailedScheduling`):

```
0/4 nodes are available: 2 Insufficient nvidia.com/gpu, 2 node(s) didn't match Pod's node affinity/selector. no new claims to deallocate, preemption: 0/4 nodes are available: 2 No preemption victims found for incoming pod, 2 Preemption is not helpful for scheduling.
```

**Taint mismatch** (pod with `nodeSelector gpu-pool=t4` and a GPU limit but no toleration):
```
0/4 nodes are available: 2 node(s) didn't match Pod's node affinity/selector, 2 node(s) had untolerated taint(s). no new claims to deallocate, preemption: 0/4 nodes are available: 4 Preemption is not helpful for scheduling.
```
Note: no "Insufficient" text at all, and "Preemption is not helpful": evicting pods can't fix a taint.

**Quota block** (namespace `quota-demo`, `ResourceQuota requests.nvidia.com/gpu: "1"`, Deployment of 2):
the second pod is never created, so **there is no Pending pod and no scheduler event**. The failure is on the ReplicaSet:
```
FailedCreate  ReplicaSet  Error creating: pods "q-6f768f45c5-xjjb2" is forbidden: exceeded quota: gpu-quota, requested: requests.nvidia.com/gpu=1, used: requests.nvidia.com/gpu=1, limited: requests.nvidia.com/gpu=1
ReplicaSet condition: ReplicaFailure=True reason FailedCreate
```

### Fake DCGM exporter
The operator ships a `nvidia-dcgm-exporter` DaemonSet on the GPU nodes (port 9400, plus a `-kwok` one). `curl` of
`/metrics` (port-forwarded to the pod on agent-0) returns only **three** DCGM series, 2 GPUs each:
`DCGM_FI_DEV_FB_FREE`, `DCGM_FI_DEV_FB_USED`, `DCGM_FI_DEV_GPU_UTIL`, labelled `gpu`, `UUID`, `modelName="Tesla-T4"`, `pod`, `namespace`.
No temperature, power, XID, ECC, clocks or NVLink counters. Values are synthetic. No dashboards built here.

## Why
- **Whole integers:** the device plugin API (`ListAndWatch` returns a list of device IDs; `Allocate` hands specific IDs to a container)
  has no notion of fractions. The kubelet reports `capacity = count of healthy devices`, extended resources must be integers and
  cannot be overcommitted (request must equal limit). The scheduler just subtracts integers; it knows nothing about memory, topology or health beyond that.
- The three failures sit at different layers: **scheduler filter** (capacity / taint) vs **API admission** (quota). That is why the quota case has no Pending pod.

## Debugging in production
1. `kubectl get pod -o wide`; no pod at all -> `kubectl describe rs/deploy` and `kubectl get events` for `FailedCreate`, then `kubectl describe quota -n <ns>`.
2. Pending -> read the *counts* in `FailedScheduling`: `Insufficient nvidia.com/gpu` (capacity) vs `untolerated taint` vs `didn't match node affinity/selector`.
3. Capacity: `kubectl describe node | grep -A8 "Allocated resources"` and which pods hold GPUs (`kubectl get pods -A -o json | jq` on `limits."nvidia.com/gpu"`).
   A node whose allocatable is 0 while hardware exists means the device plugin is down/unhealthy: check its DaemonSet.
4. Taint: `kubectl get node -o custom-columns=N:.metadata.name,T:.spec.taints` and compare with pod tolerations.

## On real GPUs
- Allocatable comes from the NVIDIA device plugin via NVML; a GPU failing health checks drops out of allocatable.
- Real DCGM exports hundreds of fields (temp, power, XID, ECC, NVLink) - see scenario 04.
- Capacity numbers would be the same arithmetic; but a "free" GPU may still be a busy/unhealthy one (the scheduler can't see that).
