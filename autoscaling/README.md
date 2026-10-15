# autoscaling/

KEDA ScaledObjects driven by queue depth (not CPU), a step load generator, and a scale-from-zero experiment.
Measured on the single-node k3s lab on 2026-10-14. Everything on sim-pool / zero-pool is **SIMULATED** (llm-d-inference-sim
v0.10.2): the pods, HPA and KEDA behaviour are real; the latencies are not.

## What's installed

| Component | Version (pinned in the Makefile) | Source of the version |
|---|---|---|
| KEDA (release `keda`, ns `keda`) | chart + app **2.20.2** (`KEDA_VERSION`) | `helm search repo kedacore/keda --versions` on 2026-10-14: latest 2.21.0, so one behind |
| ScaledObjects | `scaledobject-llamacpp.yaml`, `scaledobject-vllm-sim.yaml` (ns `inference`) | this repo |
| Scale-from-zero scratch pool | `scale-from-zero/`: Deployment `sim-zero`, EPP release `zero-pool` (llm-d-router-gateway v0.9.0, `EPP_VERSION`), ServiceMonitor, ScaledObject `sim-zero` | this repo |

Keys checked with `kubectl explain scaledobject.spec…` (CRD) and `helm show values kedacore/keda --version 2.20.2`;
KEDA Prometheus-scaler metadata keys (`serverAddress`, `query`, `threshold`, `activationThreshold`) are accepted when the
ScaledObject reports `READY True`. Resources: operator / metrics server 50m / 64Mi requests, 256Mi limits.

```bash
make keda-up                  # helm upgrade --install keda (pinned) + apply both ScaledObjects
make keda-down
.venv/bin/python autoscaling/loadgen.py --pool sim --concurrency 8 --max-tokens 96    # one cycle, sim-pool
.venv/bin/python autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64    # one cycle, llamacpp-pool
make zero-up / make probe-zero ARGS="--n 5" / make zero-down                           # scale-from-zero pool
```

The inference chart must not own `replicas` for an autoscaled backend: `llamacpp.autoscaled` / `sim.autoscaled: true`
(`values-k3s.yaml`) drops the field from the Deployment. Note: dropping a Helm-owned field under server-side apply resets
it to the default; `deploy/release.sh diff k3s` showed `inf-vllm-sim replicas: 2 → 1` on the first upgrade. Apply the
ScaledObjects first so the HPA owns the field.

**Cluster state left after the 2026-10-14 runs:** the sim-pool ScaledObject is **paused at 2 replicas**
(`kubectl -n inference annotate scaledobject inf-vllm-sim autoscaling.keda.sh/paused-replicas=2`), the sim's
pre-autoscaling size, because probes P1/P9 need ≥ 2 sim pods and min 1 would leave 1. Resume with
`kubectl -n inference annotate scaledobject inf-vllm-sim autoscaling.keda.sh/paused-replicas-`. llamacpp-pool is active
(idle = 1, its original size). The scratch `zero-pool` stays deployed at 0 replicas (one EPP pod); `make zero-down` removes it.

## ScaledObjects

| | llamacpp-pool (`inf-llamacpp`) | sim-pool (`inf-vllm-sim`) |
|---|---|---|
| Query | `sum(avg_over_time(llamacpp:requests_processing[30s])) + sum(avg_over_time(llamacpp:requests_deferred[30s]))` | `sum(vllm:num_requests_running) + sum(vllm:num_requests_waiting)` |
| Type / target | AverageValue 2 (= `--parallel 2` slots per pod) | AverageValue 2 (= `max-num-seqs 2`) |
| min / max | 1 / **3** (each pod requests 4 CPU; the 4th didn't fit) | 1 / 4 |
| pollingInterval / cooldownPeriod | 5 s / 60 s: only used for 0↔1. KEDA warns on apply: "PollingInterval is configured but is not relevant… only relevant when minReplicaCount = 0…" At min 1 the HPA reads the metric itself on its 15 s sync loop. | same |
| HPA behavior | scale-up: 0 s window, max(+2 pods, +100 %) per 15 s; scale-down: 60 s window (lab; prod 300 s+), −1 pod per 30 s | same |

Why these: scale-up reacts at once because a queued request costs a whole generation of TTFT. Scale-down waits so a short
lull doesn't drop a pod, and removes one pod at a time.

## One full cycle per pool (`loadgen.py`)

Times are seconds from the run start; load starts at 20 s. Sources: `results/<run>/log.jsonl` (sampler: deployment,
HPA `desiredReplicas`, per-pod `/metrics` every ~1 s), `hpa-events.txt` (`SuccessfulRescale`), `summary.md` (10 s steps
with queue, replicas and client TTFT p50/p95), `grafana-panel.json` (the dashboard's "replicas vs queue vs latency" panel
over the run window, `observability/dashboards/export_panels.py`).

| Step | sim-pool, SIMULATED (`results/20261014-222357-sim-pool`) | llamacpp-pool, after fix (`results/20261014-223431-llamacpp-pool`) | llamacpp-pool, first run (`results/20261014-222923-llamacpp-pool`) |
|---|---|---|---|
| command | `loadgen.py --pool sim --concurrency 8 --max-tokens 96 --idle 20 --high 150 --tail 300` | `--pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300` | same |
| load start | 20.0 | 20.0 | 20.0 |
| HPA decides (desired change) | 35.7 (1→3, metric 8), 50.7 (3→4, 2667m) | 47.6 (1→3, 4667m) | 24.6 (1→3, 5); 100.6 (3→4, 2334m) |
| new pods Ready | 38.0, 38.0; 53.1 | 49.5, 49.5 | 27.6, 27.6; 4th never (Pending) |
| first request served by new pod | 38.0, 38.6; 53.1 | 50.6, 52.8 | 27.6, 31.7 |
| load stop | 171.3 | 173.2 | 172.3 |
| scale-down | 231.1 (4→3), 261.0 (→2), 291.0 (→1) | 242.7 (3→2), 272.7 (→1) | 159.7 (4→3, under load), 220.2 (→2), 250.2 (→1) |
| requests ok / sent | 1144 / 1144 | 206 / 206 | 199 / 199 |
| client TTFT p50 before → after scale-up | 2,710 ms (1 replica, 20–30 s step) → 81–93 ms (4 replicas) | 3,600–4,612 ms (1 replica) → 572–838 ms (3 replicas) | 2,095 ms (first step) → 574–1,381 ms |

Per-step queue depth, replicas and client TTFT p50/p95 (10 s steps) are in each run's `summary.md`.

Readings:
- Decision → pod Ready is fast (sim ~2.3 s, llama.cpp ~1.9–3.0 s: the model is on the PVC and in the page cache).
  Most of the scale-up latency is detection: Prometheus scrape (5 s) + the HPA sync loop (15 s) + the query window.
- With the 30 s `avg_over_time` the llama.cpp decision came 27.6 s after load start, vs 4.6 s unsmoothed (n = 1 each;
  where the load start falls in the HPA's 15 s loop also varies). Smoothing traded detection time for no flapping.
- Scale-down starts 59–70 s after the queue empties (60 s stabilization) and removes one pod per 30 s, as configured.

### Flap / wrong scale-up on llamacpp-pool: diagnosis

- Symptom: steady 6 clients on 3 replicas; HPA went 3→4 at 100.6 s; the 4th pod `inf-llamacpp-5d577dcf66-dw5g4` never
  became Ready and was removed at 159.7 s when the HPA went back to 3.
- Evidence: `kubectl describe hpa` events / `hpa-events.txt`: `New size: 4; reason: external metric s0-prometheus(…) above target`;
  HPA metric `averageValue 2334m` × 3 pods = 7. The loadgen's own per-pod scrapes summed to 6 at every sample
  (95.8–105.7 s: e.g. `{4tf8t: 2, bblmf: 2, xtvmn: 2}`). Pod events: `FailedScheduling: 0/1 nodes are available: 1 Insufficient cpu`.
- Cause: (1) each pod is scraped by Prometheus at a different instant, so a summed gauge that changes on every request can
  count one client's finished request on pod A and its next request on pod B; with 6 clients on 3 pods the true ratio sits
  exactly at the target (2), and 7/3 exceeds the HPA's 10 % tolerance. The same over-count shows on sim-pool (Prometheus
  max 10 with 8 clients). (2) Node capacity: 3 × 4 CPU llama.cpp requests + the rest leaves no room for a 4th
  (`kubectl describe node`: 5630m of 16 CPU requested before the test).
- Fix: `maxReplicaCount: 3`, query smoothed with `avg_over_time(...[30s])`. Rerun: 1→3→1 with no extra step, 206/206 ok.

## Scale-from-zero (#10, GAPS.md P6)

Problem: at 0 replicas nothing holds requests and there are no engine metrics to trigger on.

**Option 1, EPP flow control, works** (stopped there; options 2 and 3 not tried):
- llm-d-router-gateway v0.9.0 has no flow-control CLI flag (`/app/epp --help`, captured from the image) but accepts
  `featureGates: [flowControl]` in the EndpointPickerConfig (key from the llm-d EPP flow-control docs). The EPP then logs
  `Initializing experimental Flow Control layer` instead of `…disabled, using legacy admission control`. Effective config
  logged at start: `DefaultRequestTTL:0s`, `MaxRequests: unlimited`, saturation detector `utilization-detector`.
- At 0 endpoints it **queues** the request and exports `llm_d_epp_flow_control_queue_size{inference_pool="zero-pool"}`
  (seen 0 → 2 → 3) and `llm_d_epp_flow_control_pool_saturation 1`: a metric that exists at zero.
- Limit found: **agentgateway cuts a held request at 10.0 s** with `HTTP 500: ext_proc failed: no more response messages`
  (EPP log: `ServiceUnavailable - client disconnected: request evicted from queue: request context cancelled`), 3/3 requests
  with no scale-up (`results/scale-from-zero/20261014-224047-fc-no-scale.jsonl`). `kubectl explain
  agentgatewaypolicies.spec.traffic.extProc` shows no timeout field, so the budget for detection + pod start is < 10 s.
- KEDA ScaledObject `sim-zero`: min 0, `pollingInterval 2`, Prometheus trigger on that queue (scraped every 2 s),
  `activationThreshold 0`.

| Run (`probe_zero.py --n 5 --spacing 0.5`) | Client errors | Pod created after 1st request | Pod Ready | First token at client |
|---|---|---|---|---|
| keda-run1 | 0 / 5 | 3.0 s | 4.9 s | 4.69 s |
| keda-run2 | 0 / 5 | 3.3 s | 5.4 s | 4.46 s |
| keda-run3 | 0 / 5 | 3.6 s | 5.6 s | 4.80 s |
| keda-run4 (after EPP restart) | 0 / 5 | 5.75 s | 7.5 s | 7.24 s |
| manual `kubectl scale` at 1.15 s (hold test) | 0 / 3 | 2.9 s | 4.6 s | 4.33 s |
| **control: flowControl off**, same KEDA object | **5 / 5**, immediate `HTTP 503: … failed to find endpoint candidates` | none in 20 s (no metric) | | |

(Pod Ready is from 0.5 s polling and can trail the first served request.) Raw: `results/scale-from-zero/*.jsonl`.
Earlier baseline without any hold: 7 non-200 in a scale 0→1 of llama.cpp (`scripts/README.md`, bringup_timing).

Caveats: flow control is labelled experimental in v0.9.0; the margin to the 10 s cut-off was 2.8 s in run 4 (a freshly
restarted EPP had to be rediscovered by Prometheus), so a slower backend (llama.cpp cold model load, a GPU pod) would
miss it. Only the scratch pool uses this; sim-pool and llamacpp-pool stay at min 1.

## Known limits

- One node: max replicas are bounded by its 16 CPUs (llama.cpp max 3).
- Only one cycle per configuration (n = 1); decision timing depends on where the load starts in the HPA's 15 s loop.
- No GPU: KEDA on vLLM GPU pods (and GPU utilisation as a signal) needs the T4 host or fake-gpu-operator.
- The scale-from-zero path depends on agentgateway's fixed 10 s ext_proc limit and an experimental EPP feature.
