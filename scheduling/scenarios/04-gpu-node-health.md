# Scenario 04: GPU node health: fence, drain, requeue (SIMULATED)

> **SIMULATED.** The GPUs are the fake-gpu-operator's. Nothing is detected from hardware: the "fault" is a node
> condition `GPUXidError=True` that I PATCH onto the Node status myself (`scheduling/health_run.py`). The Kubernetes
> mechanics (taint, cordon, taint-manager eviction, Kueue requeue, scheduler placement) are real; the detection is not.

## Goal
When a GPU node reports a hardware fault: stop new work landing on it, move running work off it, get Kueue batch
workloads requeued as a whole, then bring the node back when the signal clears.

## The signal I imitate
- Node Problem Detector reports *permanent* problems that make a node unusable as a `NodeCondition`, temporary ones as
  Events (kubernetes/node-problem-detector README: "node-problem-detector uses `Event` and `NodeCondition` to report
  problems to ... apiserver"). A custom-plugin monitor can be pointed at any script, so a script reading the driver /
  DCGM health result can set a condition such as `GPUXidError`. The condition name is my choice, not a standard.
- NVIDIA's XID catalog (docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html) lists e.g. XID 79 "GPU has fallen
  off the bus" and XID 48 "Double Bit ECC Error" with recommended actions (RESTART_BM / RESET_GPU / workflows). I
  fetched the page and confirmed those rows exist; I did not verify NPD ships an XID plugin (it does not appear in the
  README list I read), so on real hardware you write or deploy that check yourself (DCGM health watches, or
  `dmesg`/`journalctl` XID scraping).

## Setup
- Cluster per Task 0/1/3: two SIMULATED t4 nodes (2 GPUs each), Kueue 0.20.1 with `waitForPodsReady`.
- Workloads: `gpu-sim` Deployment (1 replica, 1 GPU, no NoExecute toleration) and a Kueue Job `health-job`
  (1 GPU, `backoffLimit: 3`, preferred affinity to the node holding the Deployment pod so both sit on the node to fail).
  After the fault only 2 GPUs remain, exactly enough for both.
- `scheduling/health_controller.py` (refuses unless context is `k3d-gpusim`; only touches nodes labelled `gpu-pool=t4`):
  1. sees `GPUXidError=True` → **cordon** + annotate `goodput/fenced-by`
  2. for each Kueue-managed Job pod on the node: set `Workload.spec.active=false`, wait for `Evicted=True`, set `true`
     (Kueue suspends the Job, deletes pods, requeues and re-admits the whole workload)
  3. taint `nvidia.com/gpu-unhealthy=xid:NoSchedule` and `:NoExecute` (taint manager evicts what is left, e.g. the Deployment pod)
  4. condition False → remove taint → uncordon (only nodes it fenced)
- Run: `make gpusim-health-run RUNS=3` (starts the controller itself). Raw: `scheduling/results/04-health-controller-run.log`.

## Expected
Deployment pod and Job pod both move to the healthy t4 node within seconds; the Workload shows an eviction/requeue; the node
returns on clear.

## What happened
### Results (3 runs, final design; node chosen = node hosting both pods; each run alternates nodes)
Command: `make gpusim-health-run RUNS=3` (2026-10-15 ~11:06-11:09 EDT). Seconds, measured by the driver polling every
~0.2 s with `kubectl` (each poll ~0.1-0.3 s), so treat ±0.5 s as noise; controller timestamps are in the log.

| run | node failed | signal → taint | taint → Deployment pod gone | pod gone → new pod Ready (other node) | signal → Ready total | clear → uncordoned+untainted |
|---|---|---|---|---|---|---|
| 1 | agent-0 | 2.32 | 0.41 | 3.96 | 6.69 | 0.74 |
| 2 | agent-1 | 2.67 | 0.22 | 0.90 | 3.79 | 0.76 |
| 3 | agent-0 | 3.44 | 0.25 | 1.68 | 5.37 | 0.76 |

"signal → taint" includes the controller's cordon + Kueue requeue (1.2-2.2 s in the log: cordoned → reactivated) because
the taint is deliberately last. Run 1's slower Ready is a cold image/pod start on agent-1; I did not isolate why.
In all 3 runs the Job's new pod landed Running on the healthy node and the Workload ended
`Admitted=True`, `Requeued=True/Reactivated`.

Kueue events (`kubectl -n team-a get events`):
```
Normal  EvictedDueToDeactivated  workload/job-health-job-2bb77  The workload is deactivated
Normal  QuotaReserved            workload/job-health-job-2bb77  Quota reserved in ClusterQueue team-a, wait time since queued was 0s
Normal  Admitted                 workload/job-health-job-2bb77  Admitted by ClusterQueue team-a, wait time since reservation was 0s
Normal  TaintManagerEviction     pod/gpu-sim-788f98c966-fzxsg   Marking for deletion Pod default/gpu-sim-788f98c966-fzxsg
```
Workload conditions after requeue: `Evicted=False/QuotaReserved`, `Requeued=True/Reactivated`, `PodsReady=True/Started`
(run 3: `Recovered`).

### Failures along the way (these are results)
1. **Stale watch events re-fenced a healthy node.** My first controller acted on queued watch objects; its own
   taint/cordon patches generated MODIFIED events, so it logged `signal_seen`/`tainted` repeatedly and re-fenced after
   `signal_cleared`. Fix: re-GET the node before acting (`handle()`).
2. **Taint first = Job falsely "Complete".** With NoExecute applied first, the sim container exits 0 on SIGTERM, the Job
   controller counts the pod Succeeded, and the Job finished (`COMPLETIONS 1/1, DURATION 3s`); Kueue never requeued it
   (workload: `Finished=True/Succeeded`). Fix: cordon → requeue the Kueue workload → *then* NoExecute. On real hardware
   a training process killed by SIGTERM usually exits non-zero or after checkpointing; whichever it does, decide the order
   deliberately.
3. **Harness left nodes fenced** when I killed a run mid-fence (controller killed before unfence; condition still True),
   so the next run's pods could not schedule (`timeout waiting for reschedule`/`deployment pod`). Fix: preflight check in
   `health_run.py` that nodes are uncordoned; manual cleanup of taint/annotation/condition.
4. **NoExecute also evicts the operator's DaemonSets** (`device-plugin`, `nvidia-dcgm-exporter`; events
   `TaintManagerEviction ... pod/device-plugin-*` in `gpu-operator`). They do not tolerate my taint, which is mostly
   desirable (fenced node stops advertising GPUs) but means the device plugin restarts on return.

## Why
- Cordon alone only stops *new* pods. NoSchedule likewise. NoExecute is what evicts running pods without a matching toleration.
- Kueue gates admission by quota but does not watch node health; it only acts when told (here: Workload `active`
  toggle), or if `waitForPodsReady` times out. I did not test `waitForPodsReady.recoveryTimeout`, so I cannot say whether it
  would requeue after a NoExecute eviction on its own. Next step.
- The Deployment case needs no controller help: the taint manager evicts, the ReplicaSet recreates, the scheduler places it
  on the other t4 node (it was the only one without the taint).

## Runbook
**Detection.** What to alert on: Xid errors in kernel logs (79 fell off bus, 48 DBE, 95 uncontained ECC, per NVIDIA's XID
catalog); DCGM health watches (`dcgmi health`) for ECC/PCIe/NVLink/thermal; `DCGM_FI_DEV_XID_ERRORS` (real dcgm-exporter
only; the fake exporter here has just `FB_FREE/FB_USED/GPU_UTIL`, so nothing here can fire it). Publish as a Node condition
(NPD custom plugin) so controllers can key off one object.
**Fence.** Cordon, then taint NoSchedule; NoExecute last (see failure 2).
**Drain.** *Inference (Deployments/EPP pools)*: NoExecute is fine, replacements start elsewhere; ensure
spare capacity and PDBs so the pool is not emptied; the gateway/EPP drops the endpoint when the pod goes. *Batch (Kueue)*:
requeue the workload as a whole so quota is released and gangs restart together; for long training jobs trigger a checkpoint
first if the GPU is merely degraded rather than dead. Note the 2-node limit here: one fault halves capacity.
**Remediation.** On real nodes: reset GPU / reboot per the XID recommended action, re-run health check, then clear the condition.
**Return to service.** Clear condition → controller removes taint + uncordons (0.7 s here); verify device plugin re-advertises
`nvidia.com/gpu` allocatable before relying on the node.

## What's different on real GPUs / what is simulated
- Detection, XID/ECC/NVLink/PCIe behaviour, DCGM health, GPU reset, driver reload: **not simulated**; condition injected by hand.
- Real GPU faults hang or kill processes ungracefully; pods usually go `Error`/stuck Terminating, not a clean SIGTERM exit 0.
- Real image pulls / model loads make "evicted → Ready" minutes, not 1-4 s (sim image is cached, no model).
- Timings are 3 runs on one machine with polling; not a benchmark.
