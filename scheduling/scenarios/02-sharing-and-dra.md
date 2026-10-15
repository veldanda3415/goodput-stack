# 02 - GPU sharing (time-slicing / MPS / MIG) and DRA vs the device plugin (SIMULATED)

> **SIMULATED.** fake-gpu-operator 0.2.1 advertises GPUs; nothing runs on a GPU and nothing is
> isolated or time-multiplexed. What is real is the Kubernetes API behaviour (ResourceSlices, claims,
> allocation, scheduling). 2026-10-15, k3d `gpusim`, k3s v1.36.2+k3s1.

## Goal
(a) Legacy time-slicing with N replicas per GPU; (b) DRA: DeviceClass + ResourceClaimTemplate, and one ResourceClaim shared by two pods.

## Part A - time-slicing replicas: NOT supported by the pinned operator (no result faked)
Searched the v0.2.1 source tree (`grep -rIl -i "time-slic\|timeslic"`): hits are only the **DRA** plugin
(`internal/dra-plugin-gpu/state.go`) and its e2e fixture. The legacy device plugin / chart values
(`deploy/fake-gpu-operator/values.yaml`) have no `replicas`/`sharing` setting; the only related
README item is "simulated GPU fractioning readiness" (a node condition, "does not provide fraction enforcement").
So no "4 pods on one GPU via the device plugin" was produced. With the **real** NVIDIA device plugin the config is
(source: [NVIDIA/k8s-device-plugin README, "With CUDA Time-Slicing"](https://github.com/NVIDIA/k8s-device-plugin#with-cuda-time-slicing);
[GPU Operator "Understanding Time-Slicing GPUs"](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html)):

```yaml
version: v1
sharing:
  timeSlicing:
    renameByDefault: false          # true => advertised as nvidia.com/gpu.shared
    failRequestsGreaterThanOne: true
    resources:
    - name: nvidia.com/gpu
      replicas: 4
```
Per those docs: a node with 2 GPUs then advertises `nvidia.com/gpu: 8`, label `nvidia.com/gpu.replicas=4`, and product label gets the `-SHARED` suffix
(unless `renameByDefault`). Requesting >1 time-sliced GPU does not give proportional compute.

## Part B - DRA on the operator's own DRA mode
- Mode switch: overlay [fake-gpu-operator.dra.values.yaml](../fake-gpu-operator.dra.values.yaml) (`make gpusim-operator MODE=dra`), from README "Enable DRA plugin" (v0.2.1).
  It **replaces** the device plugin: with it applied `nvidia.com/gpu` allocatable was `"0"` on the t4 nodes. I restored `MODE=deviceplugin` afterwards (allocatable back to 2).
- **Failure found:** first `helm upgrade` with DRA left the kubelet-plugin DaemonSet at `DESIRED 0`, no ResourceSlices. Cause: `draPlugin.kubeletPlugin.tolerations` defaults to `[]`, so our
  `nvidia.com/gpu=present:NoSchedule` taint blocked it. Fix: add the toleration (in the overlay). (My first overlay also nested `kubeletPlugin` under `devicePlugin` - `helm get values` showed it; fixed.)
- API checks: `kubectl explain resourceclaim.spec.devices.requests.exactly` (resource.k8s.io/v1 served by k3s v1.36.2). DeviceClass `gpu.nvidia.com` is created by the chart
  (CEL `device.driver == 'gpu.nvidia.com' && device.attributes['gpu.nvidia.com'].type == 'gpu'`, plus `extendedResourceName: nvidia.com/gpu`).

ResourceSlices (`kubectl get resourceslices`): one per t4 node, driver `gpu.nvidia.com`, pool = node name, 2 devices each:
```
k3d-gpusim-agent-0-gpu.nvidia.com-km7km   k3d-gpusim-agent-0   gpu.nvidia.com   k3d-gpusim-agent-0
k3d-gpusim-agent-1-gpu.nvidia.com-w26k5   k3d-gpusim-agent-1   gpu.nvidia.com   k3d-gpusim-agent-1
# a device:
- attributes: {gpu.nvidia.com/productName: {string: Tesla-T4}, gpu.nvidia.com/type: {string: gpu}, gpu.nvidia.com/uuid: ..., model: ..., uuid: ...}
  capacity: {memory: {value: 15Gi}}
  name: gpu-ee76d285-1c50-5339-8d03-9714b7ed32bd
```
(Note `15Gi` vs the 15360 MiB configured: same number, different unit.)

Manifests: [dra-template.yaml](../manifests/dra-template.yaml), [dra-shared-claim.yaml](../manifests/dra-shared-claim.yaml).

**Template claim:** pod `from-template` -> generated claim `from-template-gpu-brplr`, `allocated,reserved`, device on `k3d-gpusim-agent-1`:
```
allocation: {devices: {results: [{device: gpu-b2d4b513-..., driver: gpu.nvidia.com, pool: k3d-gpusim-agent-1, request: gpu}]}}
reservedFor: [{name: from-template, resource: pods}]
```
**Shared claim** (`resourceClaimName: shared-gpu`, CEL selector `productName == 'Tesla-T4'`, opaque `TimeSlicing` config): `shared-0` and `shared-1` both Running on agent-0,
claim `allocated,reserved`, **one** device, two pods in `reservedFor`:
```
- device: gpu-ee76d285-1c50-5339-8d03-9714b7ed32bd  driver: gpu.nvidia.com  pool: k3d-gpusim-agent-0  request: gpu
reservedFor: [{name: shared-0, resource: pods}, {name: shared-1, resource: pods}]
```
**DRA exhaustion** (claim consumers: 1 template + 1 shared = 2 GPUs; 3 more template pods -> 4 GPUs used, the 3rd extra Pending):
```
extra-3: 0/4 nodes are available: 2 cannot allocate all claims, 2 node(s) didn't match Pod's node affinity/selector. still not schedulable, preemption: 0/4 nodes are available: 4 Preemption is not helpful for scheduling.
shared-1 (transient, first pod being allocated): resource claim dra-demo/shared-gpu is in the process of being allocated.
```
Compare scenario 01: `Insufficient nvidia.com/gpu` becomes `cannot allocate all claims`.

## Expected vs happened
Expected the operator to have a DRA mode (yes, with the toleration fix) and no legacy time-slicing (confirmed). The TimeSlicing opaque config was *accepted* on the claim and pods ran; the
plugin's code only turns it into an env var (`GPU_DEVICE_<id>_TIMESLICE_INTERVAL`, `state.go`). I could not read it from the pod: the sim image has no `env` binary (`exec: "env": executable file not found`), so
even that is unverified here.

## Time-slicing vs MPS vs MIG (NVIDIA docs)
| | Time-slicing | MPS | MIG |
|---|---|---|---|
| Mechanism | CUDA time-slice interleaving of replicas of one GPU | control daemon, space partitioning (SM + memory) | hardware partitions into predefined GPU instances |
| Memory protection | **none**: every workload sees all memory | per-client memory limit (equal fraction of device memory) enforced by the daemon (device-plugin README) | hardware-isolated memory |
| Fault isolation | **none**: one crash takes them all (device-plugin README) | shared server process (no hardware fault isolation per MPS docs summary above) | hardware-level fault isolation (GPU Operator docs) |
| Use | dev/notebooks, bursty small inference, GPUs without MIG (e.g. T4) | many small cooperative CUDA jobs, better utilization than time-slicing | multi-tenant with guarantees, A100/H100-class |
Sources: NVIDIA k8s-device-plugin README ("Shared Access to GPUs"), GPU Operator time-slicing page, [MPS docs](https://docs.nvidia.com/deploy/mps/latest/index.html).
MIG support list for T4 (not supported; MIG is Ampere+) is from my knowledge of NVIDIA's MIG user guide, **not re-fetched this session**. Time-slicing and MPS are mutually exclusive in the device plugin, and sharing is per node, not per GPU.

## What DRA adds over the device plugin
- **Claims** as API objects with lifecycle (`ResourceClaim`, `ResourceClaimTemplate`), allocation recorded in `status.allocation`, who uses it in `reservedFor` - the scheduler allocates, not just counts.
- **Selection by attributes/capacity** with CEL (`productName == 'Tesla-T4'`, memory) instead of node labels + `nodeSelector`.
- **Sharing** a device between pods/containers by referencing one claim (shown above); per-claim config via opaque parameters to the driver (time-slicing/MPS-style settings).
- **Structured parameters**: devices are published as ResourceSlices (attributes, capacity) so the scheduler can reason without calling the driver.
- Device plugin: integer counts, opaque to the scheduler, per-node sharing config via ConfigMap.

## Debugging in production
`kubectl get resourceslices`, `kubectl get resourceclaims -A`, `kubectl describe resourceclaim`, driver kubelet-plugin DaemonSet (check tolerations as above!), pod events (`cannot allocate all claims`).

## Honest caveats
- No sharing of real compute or memory occurred; "2 pods on one GPU" is a bookkeeping result (2 pods in `reservedFor`).
- Time-slicing behaviour (latency interleaving, no memory isolation, OOM blast radius) cannot be shown without a GPU.
- DRA drivers on real nodes need the NVIDIA DRA driver; this is the fake plugin's own implementation (derived from kubernetes-sigs/dra-example-driver per its templates), so attribute names (`gpu.nvidia.com/productName`) are the fake's.
- DRA and device-plugin modes are mutually exclusive here; the repo's other scenarios run in device-plugin mode.
