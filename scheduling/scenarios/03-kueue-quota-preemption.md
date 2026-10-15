# 03 - Kueue: quotas, borrowing, preemption, gang admission (SIMULATED GPUs)

> **SIMULATED.** 4 fake GPUs (fake-gpu-operator 0.2.1, 2 per t4 node); pods are llm-d-inference-sim.
> Kueue's accounting and eviction are real; no workload used a GPU. 2026-10-15, k3d `gpusim`, k3s v1.36.2+k3s1.

## Goal
Per-team GPU quotas with borrowing, reclaim by preemption, priority inside a team, and all-or-nothing admission for a multi-pod job.

## Setup
- **Kueue chart 0.20.1 (app v0.20.1)**, `helm pull oci://registry.k8s.io/kueue/charts/kueue --version 0.20.1` (releases via GitHub API: v0.20.2 was published the same day, v0.20.1 a week earlier; I pinned the older one).
  Values = the chart's default config ([kueue.values.yaml](../kueue.values.yaml)); `make gpusim-kueue`.
- Objects: [kueue-queues.yaml](../manifests/kueue-queues.yaml) (fields checked with `kubectl explain` on the installed v1beta2 CRDs):
  ResourceFlavor `gpu-t4` (nodeLabels `gpu-pool=t4` + toleration for the taint), ClusterQueues `team-a`/`team-b` in cohort `gpu-cohort`, nominal 2 GPUs each
  (`reclaimWithinCohort: Any`, `withinClusterQueue: LowerPriority`), LocalQueue `lq` in namespaces `team-a`/`team-b`, WorkloadPriorityClasses `low`=100, `high`=1000.
- Jobs from [kjob.py](../kjob.py): sim pods, `limits nvidia.com/gpu`, label `kueue.x-k8s.io/queue-name: lq`. No toleration in the Job: the flavor injects it.

## Failure first: wrong reason for "over quota" (symptom -> evidence -> cause -> fix)
First run, a 5-GPU job and a 3-GPU job both stayed suspended with
`QuotaReserved=False reason=NoMatchingFlavor: couldn't assign flavors to pod set main: resource memory unavailable in ClusterQueue`.
Cause: the ClusterQueue only covered `nvidia.com/gpu`, but pods request cpu/memory too, and Kueue 0.20.1 refuses a workload that requests a resource the queue does not declare
(the chart's commented `resources.quotaCheckStrategy: "BlockUndeclared"`; I did not set it, so this is the observed default). Fix: declare `cpu` and `memory` in `coveredResources` with generous quotas.
This also looks like "over quota" from the outside but is a config error: read the **reason**, not just "suspended".

## 1. Over-quota job stays suspended
`team-a` job `over-quota`, 5 pods x 1 GPU (cohort total 4):
```
suspend=true            # Job
No resources found in team-a namespace.   # no pods
job-over-quota-fdc49   lq   (RESERVED IN empty)   ADMITTED False
QuotaReserved=False reason=ExceedsMaxQuota msg=couldn't assign flavors to pod set main: insufficient quota for nvidia.com/gpu in flavor gpu-t4, previously considered podsets requests (0) + current podset request (5) > maximum capacity (4)
Admitted=False reason=NoReservation
```
`ExceedsMaxQuota` = can never fit (even borrowing everything). `WaitingForQuota` (below) = fits eventually, not now.

## 2. Borrowing
team-b idle; team-a submits 3 x 1 GPU (nominal 2):
```
job-borrower-d8e8f   lq   team-a   Admitted True
event: Quota reserved in ClusterQueue team-a ... Flavors considered: main: gpu-t4(Fit;borrow=1)
ClusterQueue team-a  nvidia.com/gpu total=3 borrowed=1       (kubectl get clusterqueue team-a -o jsonpath='{.status.flavorsUsage}')
admission: {"clusterQueue":"team-a","podSetAssignments":[{"count":3,"flavors":{"nvidia.com/gpu":"gpu-t4",...},"resourceUsage":{"nvidia.com/gpu":"3",...}}]}
```
3 pods Running (agent-0 x2, agent-1 x1).

## 3. Reclaim by preemption
team-b submits 2 x 1 GPU (its nominal) at 10:49:40; 25 s later:
```
team-a  job-borrower-d8e8f   Admitted False       (Job suspended, pods deleted)
team-b  job-reclaimer-4aeb1  Admitted True        (2 pods Running)
team-a Workload: Evicted=True reason=Preempted
  msg=Preempted to accommodate a workload (UID: bceacd9d-..., JobUID: 60b90160-...) due to reclamation within the cohort; preemptor path: /gpu-cohort/team-b; preemptee path: /gpu-cohort/team-a
team-a Workload: Preempted=True reason=InCohortReclamation ; Requeued=True reason=Preempted
team-a Workload: QuotaReserved=False reason=WaitingForQuota msg=... insufficient unused quota for nvidia.com/gpu in flavor gpu-t4, 1 more needed
events:  team-b PreemptedWorkload  Preempted workload team-a/job-borrower-d8e8f ... ; team-b WaitingForPreemptedWorkloads ... Pending the preemption of 1 workload(s)
         team-a EvictedDueToPreempted / Preempted (workload/job-borrower-d8e8f); job/borrower: Suspended, Stopped
```
The **whole** 3-pod workload was evicted (not just the 1 borrowed GPU's pod) and requeued; it is gang-evicted because the workload is the unit.

### Priority inside a team
team-a `low-job` (2 GPUs, `low`) admitted; then `high-job` (2 GPUs, `high`) with no spare capacity (team-b holds 2):
```
job-high-job-ffebc  priority 1000 (high)  Admitted True
job-low-job-b6460   priority  100 (low)   Admitted False
low Workload: Evicted=True reason=Preempted msg=Preempted ... due to prioritization in the ClusterQueue; preemptor path: /gpu-cohort/team-a; preemptee path: /gpu-cohort/team-a
event: PreemptedWorkload workload/job-high-job-ffebc  Preempted workload team-a/job-low-job-b6460 ...; preemptor effective priority: 1000 (base: 1000, boost: 0); preemptee effective priority: 100
```

## 4. Gang / all-or-nothing
**(a) quota gate.** team-b holds 2 GPUs; team-a submits 3 x 1 (cohort has 2 unused):
```
job-gang-a-569d9   RESERVED IN (empty)  ADMITTED False
No resources found in team-a namespace.            # zero pods created
WaitingForQuota: ... insufficient unused quota for nvidia.com/gpu in flavor gpu-t4, 1 more needed
```
Nothing started: the Job stays suspended until the whole workload fits quota.

**(b) the gap Kueue can't see: physical capacity.** Two non-Kueue pods (`gpu-sim` Deployment, default ns) held 2 GPUs, invisible to Kueue's quota. `gang-b` (3 x 1) was admitted by quota (QuotaReserved/Admitted True) but only 2 GPUs were physically free. Default config, after 70 s:
```
gang-b-9m28j Running ; gang-b-kbhd2 Running ; gang-b-htp7p Pending
PodsReady=False reason=WaitForStart msg=Not all pods are ready or succeeded ; Admitted=True
FailedScheduling: 0/4 nodes are available: 2 Insufficient nvidia.com/gpu, 2 node(s) didn't match Pod's node affinity/selector. ...
```
= a **partial start**: 2 GPUs held by a job that cannot run. (It would stay like this; I observed 70 s.)

**(c) `waitForPodsReady`** ([kueue.waitforpods.values.yaml](../kueue.waitforpods.values.yaml): `timeout: 60s`, `blockAdmission: false`, requeuing `timestamp: Eviction`, `backoffLimitCount: 1`, `backoffBaseSeconds: 10`;
keys from the chart's commented defaults). `gang-c` submitted 10:54:01:
```
+~60 s  Stopped: Exceeded the PodsReady timeout team-a/job-gang-c-65e3d ; workload event EvictedDueToPodsReadyTimeout   (pods deleted, GPUs released)
        Requeued=True reason=BackoffFinished ; requeueState {"count":1}  -> readmitted, same shortage, pods again 2 Running + 1 Pending
+~2 min  spec.active=false ; Evicted=True reason=DeactivatedDueToRequeuingLimitExceeded ; QuotaReserved=False reason=Deactivated ; Job suspend=true, no pods
```
What it adds: a job that is admitted but can't actually get all its pods running is evicted and requeued with backoff instead of squatting on GPUs, and after the limit it is deactivated (needs a human).
What it does not do: it does not make scheduling atomic (the 2 pods did start for up to 60 s) and it does not know *why* pods are not ready.

Not run: **topology-aware scheduling stretch** (skipped for time; see README).

## Why
Kueue gates *admission* by quota (it unsuspends the Job); kube-scheduler still does placement. So quota-gang is atomic, placement-gang is not: only a gang scheduler (KAI/Volcano
PodGroup) holds pods back until all can be placed. Borrowing is allowed up to unused cohort quota; reclaim preempts workloads that are using more than their nominal quota.

## Debugging in production
`kubectl get workload -A`, `kubectl describe workload` (conditions: `QuotaReserved`, `Admitted`, `Evicted`, `PodsReady`, `Requeued`), `kubectl get clusterqueue -o yaml` (`flavorsUsage`, `borrowed`),
events on Workload and Job. Distinguish `NoMatchingFlavor` (config/undeclared resource/node-label mismatch), `ExceedsMaxQuota` (can't ever fit), `WaitingForQuota` (queued), `Preempted` (look at preemptor path).
Admitted-but-Pending pods: it is kube-scheduler (`FailedScheduling`, scenario 01), not Kueue.

## Kueue vs KAI Scheduler vs Volcano (their READMEs, fetched 2026-10-15)
- **Kueue** ([kubernetes-sigs/kueue](https://github.com/kubernetes-sigs/kueue)): "job-level manager that decides when a job should be admitted to start ... and when it should stop"; works with the default kube-scheduler. Pick it for multi-tenant quotas, borrowing/preemption and many job types with minimal change to the scheduler.
- **KAI Scheduler** ([NVIDIA/KAI-Scheduler](https://github.com/NVIDIA/KAI-Scheduler)): a scheduler (replaces placement) with gang/batch scheduling "all pods in a group are scheduled simultaneously or not at all", hierarchical queues, bin-packing/spread, topology-aware and GPU-sharing features. Pick it when GPU placement quality (gang placement, fractions, topology) is the problem.
- **Volcano** ([volcano-sh/volcano](https://github.com/volcano-sh/volcano)): "Kubernetes-native batch scheduling system" extending kube-scheduler, built on kube-batch, strong HPC/Spark/MPI/Ray ecosystem with PodGroups. Pick it for HPC/big-data style batch with its own job CRD.
- Rule of thumb (my reading, not from the docs): Kueue for who-gets-quota, KAI/Volcano for atomic placement; Kueue can sit on top of either scheduler's pods in principle but I did not test combinations.

## On real GPUs
- Real placement can fail on topology (NVLink/same-node), GPU health, MIG profiles: quota says yes, scheduler says no (case 4b becomes common).
- Preempted workloads need checkpointing; eviction is a SIGTERM + grace period, and real models take minutes to reload (here: seconds, the sim has no model).
- Quota here counts a fake extended resource; on real clusters count `nvidia.com/gpu` the same way, but MIG/time-sliced resources are separate resource names to cover in the ClusterQueue.
