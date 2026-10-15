# Gateway / EPP gaps

What the gateway layer (agentgateway v1.6.0 + llm-d-router-gateway EPP v0.9.0, two InferencePools)
does and does not do, tested on the k3s lab (single node `ravi-home`, ns `inference`, LB 192.168.117.204).

- **sim-pool**: 2 × llm-d-inference-sim v0.10.2 (max-num-seqs 2, ITL 16.3 ms, random mode). Results are **SIMULATED**.
- **llamacpp-pool**: 1 × llama.cpp b11146, Qwen2.5-0.5B Q4_K_M, `--parallel 2`, `--threads 4` (real engine, CPU).
- Runs: 2026-10-05. n is small (lab). Latency differences under ~10 ms are noise at these n.

| # | Gap | Verdict | Status |
|---|---|---|---|
| P1 | Load-aware routing | works (sim-pool) | closes #18 |
| P2 | EPP outage | FailOpen works, routing goes load-blind silently | mitigation open |
| P3 | Client disconnect | **not propagated by the gateway within 15 s** | new issue (upstream draft below) |
| P4 | llama.cpp KV / capacity signal | missing; KV scorer contributes nothing | #15 |
| P5 | Pool choice by prompt size / SLO | header only | #11 (design) |
| P6 | Admission / scale-from-zero | engine queues, gateway doesn't | #10 (design) |
| P7 | Gateway pod killed mid-stream | graceful delete drains the stream; hard kill cuts it, slot freed ~2.5 s. 1 replica: ~1 s of refused connections; **2 replicas + PDB: 0 failed new requests**, the killed pod's stream is still lost | #20 (2 replicas in chart), HA → #19 |
| P9 | Burst inside one EPP metrics refresh | no 8/0 herding; per-run split up to 7/1 vs always 4/4 when spaced (sim-pool, SIMULATED) | #22 |

---

## P1 — Does the EPP route by load?

**Question.** When one backend is busy, does the EPP send new requests elsewhere, based only on what it scrapes from the engine's `/metrics`?

**Method.** `scripts/probe_p1_saturation.py` (sim-pool). Saturate pod A **directly** through a port-forward, so the gateway and the EPP never see that traffic: 8 long requests (1000 tokens, `ignore_eos`). Wait for A to show `waiting > 0`, then 1 s settle. Then send 20 short gateway requests with **unique prompts** (UUID), which neutralises the prefix-cache scorer. Count `selected_endpoint=` per pod in the gateway log. Control: `--no-saturate`, which now refuses to run unless A reads running=0 / waiting=0.

**Evidence (SIMULATED).**

| Run | A gauges at send time | Picks A / B | HTTP |
|---|---|---|---|
| saturated (2026-10-05, earlier) | running 2 / waiting 6 | **0 / 20** | 200×20 |
| control (earlier, A verified 0/0) | 0 / 0 | 9 / 11 | 200×20 |
| saturated (this session) `probe_p1_saturation.py` | running 2 / waiting 6 | **0 / 20** | 200×20 |
| control (this session) `probe_p1_saturation.py --no-saturate` | 0 / 0 | 10 / 10 | 200×20 |
| control right after a saturated run (this session) | 2 / 6 | refused: `control invalid: A not idle {'running': 2.0, 'waiting': 6.0}` | — |

The first control attempt (earlier) was invalid: A was still draining (running 2 / waiting 4). That is why the guard exists.

**Verdict.** The EPP scrapes engine metrics and the queue-scorer steers. **Closes #18 for sim-pool.** llamacpp-pool was shown earlier with `scripts/probe_epp_scrape.sh`: the EPP reads `llamacpp:requests_*` via the pod label `llm-d.ai/engine-type=llamacpp`.

**Caveat.** This proves steering away from a backed-up pod. It says nothing about balance quality at moderate load or with real prefix reuse.

---

## P2 — What happens when the EPP is gone? (`failureMode: FailOpen`)

**Question.** Does the gateway keep serving if the EPP is unavailable, and what does that cost?

**Method.** `scripts/probe_p2_failopen.py --n 50`: baseline → `kubectl scale deploy/sim-pool-epp --replicas=0` (EPP gone, connection refused) → scale back to 1. Each phase sends 50 sequential requests, `ignore_eos`, 5 tokens, unique prompts. Picks are counted from the gateway log (`endpoint=`).

**Evidence (SIMULATED backends, 2026-10-05).**

| Phase | Codes | p50 | Picks | Gateway log |
|---|---|---|---|---|
| EPP up | 200×50 | 117 ms | via EPP | `inferencepool.selected_endpoint` present |
| EPP down | 200×50 | 99 ms | 28 / 22 | **no `inferencepool.selected_endpoint`**: the gateway's own LB |
| EPP restored | 200×50 | 105 ms | via EPP | present again |

EPP pod Ready 2.0 s after scale-up. An earlier n=20 run (80 / 56 / 75 ms) was discarded: it had no `ignore_eos`, so output length was random.

**Verdict.** agentgateway honours FailOpen: no errors. During the outage, routing is **load-blind and silent**: clients see 200s, and only the absence of `selected_endpoint` in the log shows it. The EPP hop costs roughly 10–20 ms p50 in this lab. At n=50 that cannot be separated from noise (~10 ms).

**Mitigation.** Alert on EPP availability and ext-proc errors / missing `selected_endpoint`. In prod: EPP replicas ≥ 2 + PodDisruptionBudget. FailClose only where load-blind routing is worse than errors.

**Untested.** EPP **hung** (accepts the connection, never responds): how long the gateway waits, and whether it then fails open.

---

## P3 — Does a client disconnect free the engine slot?

**Question.** If a client goes away mid-generation, does llama.cpp stop generating, both direct and through the gateway?

**Method.** `scripts/probe_p3_disconnect.py [--direct]` (llamacpp-pool, real engine). Two long requests occupy both slots (`max_tokens 1500`, `ignore_eos`). After 3 s one client is cancelled, and `llamacpp:requests_processing` is sampled every 0.5 s for 15 s. Without `--direct` the requests go through the gateway with `x-pool: cpu`.

**Evidence (2026-10-05).**

| Path | stream | non-stream |
|---|---|---|
| direct (port-forward to pod) | slot freed after ~1.5 s | not freed in 15 s |
| via gateway | **not freed in 15 s** | not freed in 15 s |

**Sim repeat (SIMULATED, this session, `--backend sim`, same method):**

| Path | stream | non-stream | Command |
|---|---|---|---|
| direct (pod IP) | not freed in 15 s | not freed in 15 s | `probe_p3_disconnect.py --backend sim --direct` |
| via gateway (sim-pool, `running` summed over both pods) | not freed in 15 s | not freed in 15 s | `probe_p3_disconnect.py --backend sim` |
| direct, 30 s window | freed at ~21.6 s | freed at ~21.6 s | `probe_p3_disconnect.py --backend sim --direct --watch 30` |

21.6 s is natural completion: 1500 tokens × 16.3 ms ITL ≈ 24.5 s, minus the 3 s hold. So llm-d-inference-sim v0.10.2
**never cancels on client disconnect**, even direct and streamed. The sim can't test cancellation propagation, and in sim
experiments an abandoned request keeps counting in `running` until `max_tokens`.

An earlier gateway run without `ignore_eos` showed "freed at 6 s". That was natural EOS, not cancellation, which is why `ignore_eos` is now mandatory in the probe. The sim had already shown the same in P1: waiting 6→4 after the client cancelled (earlier run), and in this session running 2 / waiting 6 immediately after the P1 load tasks were cancelled.

**Verdict.** llama.cpp cancels when a **stream write fails** (the sim never does); non-stream has nothing to write until the end, so it never notices. agentgateway **does not propagate the downstream close upstream within 15 s**. Through the gateway, engine-side cancellation is effectively disabled, even for streams. (Wording: "not within 15 s", not "never".)

**Impact.** Abandoned generations hold slots and KV until `max_tokens`. That wastes capacity and inflates `running`/`deferred`, which skews EPP queue scoring and, later, KEDA scaling signals.

**Mitigation.**
- **Proxy-side propagation.** No agentgateway setting for closing the upstream on downstream disconnect was found in the docs. Its issue tracker has MCP/SSE-session disconnect cleanup ([#1561](https://github.com/agentgateway/agentgateway/pull/1561), [#1536](https://github.com/agentgateway/agentgateway/issues/1536)) but nothing for plain HTTP/LLM backends. → upstream issue (draft below).
- **Deadlines.** HTTPRoute `timeouts.request` (or AgentgatewayPolicy `traffic.timeouts.request`) is supported ([docs](https://agentgateway.dev/docs/kubernetes/latest/resiliency/timeouts/request/)). It bounds the worst case, but it covers the whole response, so it must exceed the longest legitimate stream. Not tested here.
- **Cap `max_tokens`** at the gateway/client; prefer streaming (it is the only mode the engine can cancel).

**Upstream issue draft (agentgateway).**
> *Title:* Downstream client disconnect is not propagated to the upstream HTTP backend (LLM streaming)
> *Setup:* agentgateway v1.6.0, Gateway API + InferencePool (llm-d EPP), backend llama.cpp server (`stream: true`).
> *Repro:* start a streaming chat completion through the gateway, kill the client after 3 s, watch `llamacpp:requests_processing` on the backend.
> *Expected:* upstream connection closed → backend detects the write failure and frees the slot (it does in ~1.5 s when the client connects directly).
> *Actual:* the slot stays busy for ≥ 15 s (until generation ends).
> *Ask:* close/reset the upstream stream when the downstream closes, or document a setting for it.

---

## P4 — llama.cpp exposes no KV-cache or capacity signal

**Question.** Can the EPP's KV-cache scorer and capacity reasoning work for llama.cpp?

**Method.** Scrape llama.cpp `/metrics` and check which metric names exist (this session):

```
kubectl -n inference port-forward svc/inf-llamacpp 28080:8080 &
curl -s localhost:28080/metrics | grep -E '^# TYPE'
```

**Evidence.** Metric names present (b11146):

```
counters: llamacpp:prompt_tokens_total, prompt_tokens_cached_total, prompt_seconds_total, tokens_predicted_total,
          tokens_predicted_seconds_total, n_decode_total, n_tokens_max, spec_decode_num_draft_tokens_total,
          spec_decode_num_accepted_tokens_total, spec_decode_num_drafts_total
gauges:   llamacpp:prompt_tokens_seconds, predicted_tokens_seconds, requests_processing, requests_deferred,
          n_busy_slots_per_decode
```

There is **no KV-cache usage** gauge and **no total-slot** gauge. `n_busy_slots_per_decode` is not a capacity signal: it read `1.61203` while the server was idle (processing 0, deferred 0; `kubectl exec … curl localhost:8080/metrics`, 2026-10-05T19:42Z), so it is an average over past decodes, not the current state. A second idle scrape (2026-10-13T01:40Z, `kubectl -n inference exec <llamacpp pod> -c llama-server -- curl -s localhost:8080/metrics`) read `1.74442` with processing 0 / deferred 0: it moved between two idle scrapes, which fits a cumulative average. `GET /slots` is enabled (HTTP 200) and returns one object per slot with `n_ctx` (2048 = `-c 4096` / `--parallel 2`) and `is_processing`.

**Verdict.** In the llamacpp-pool engineConfig `kvUsageSpec: ""`, so the kv-cache-utilization-scorer contributes nothing (kept at weight 2 on purpose to show that). The EPP also can't tell a 2-slot server from an 8-slot one: `requests_processing=2` means "full" on one and "25 %" on the other.

**Mitigation.** (a) A `/slots` scraper data-source plugin for the EPP (slot count, busy slots, per-slot ctx). (b) An upstream llama.cpp metric (`kv_cache_usage_ratio`, `n_slots`). → **#15**, upstream PR after the break.

---

## P5 — Pool choice by prompt size / latency SLO (#11)

**Question.** Can a request be sent to the right *pool* (CPU llama.cpp vs GPU/sim) based on its size or latency SLO?

**Today.** Only by an explicit client header: the llamacpp-pool HTTPRoute matches `/` + `x-pool: cpu`, and everything else goes to sim-pool. The EPP picks an endpoint *within* a pool; nothing chooses *between* pools from the request body or an SLO.

**Options.**

| Option | How | Pro | Con |
|---|---|---|---|
| (a) client header (current) | client sets `x-pool` | trivial, explicit, testable | client must know the topology; no protection from misuse |
| (b) body-based routing (BBR) | ext-proc before routing writes a header from the body; HTTPRoute matches the header | standard GIE pattern; routing stays in HTTPRoute | GIE's BBR extracts the `model` field into `X-Gateway-Model-Name` ([GKE doc](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/configure-body-based-routing)). Prompt size / SLO would need a custom BBR plugin. Not verified with agentgateway. |
| (c) EPP custom filter | one pool with all backends; filter by prompt size / SLO header | full request context, reuses EPP metrics | merges pools with different engines/metrics into one EPP; blurs per-pool scaling |

**Recommendation.** Keep (a) now, and move to (b) when needed: a BBR-style ext-proc that sets `x-pool` from prompt-token estimate and an optional `x-slo-ttft-ms` header. Pool selection stays declarative in HTTPRoute, each pool keeps its own EPP and scaling, and the client header remains as an override. (c) is rejected: it couples heterogeneous engines in one scheduler.

---

## P6 — Admission control / scale-from-zero (#10)

**Question.** Under overload, or with 0 replicas, where does a request wait?

**Evidence.** Both EPPs log `"Experimental Flow Control layer is disabled, using legacy admission control"` (`kubectl -n inference logs deploy/sim-pool-epp | grep -i "flow control"`, same for llamacpp-pool-epp). Under overload the request queues **in the engine** (`requests_deferred`), not at the gateway: in the earlier 7b evidence a request queued ~40 s inside llama.cpp.

**Verdict.** No gateway-level queue or shedding today. With 0 replicas there is nothing to queue at, and the request fails.

**Design notes.** Scale-from-zero needs (1) KEDA scaling on EPP/engine queue metrics, and (2) an activator-style hold: the gateway/EPP keeps the request while a pod starts (warm bring-up ≈ 4 s, see `scripts/README.md`), with a deadline. Evaluate EPP Flow Control (queueing + fairness at the EPP) as that hold before building one. P3 matters here: abandoned requests would inflate the queue signal KEDA scales on.

---

## P7 — Gateway pod killed mid-stream (#20)

**Question.** If the single agentgateway pod dies while a stream is in flight, what does the client see, does the engine slot free up, and how fast does the gateway come back?

**Method.** `scripts/probe_p7_gateway_kill.py` (`make probe-p7`), llamacpp-pool (llama.cpp cancels on a failed stream write; the sim never cancels, P3). Each run starts from one Ready gateway pod and `requests_processing 0`. One streaming request through the gateway (`x-pool: cpu`, `max_tokens 1900`, `ignore_eos`). After K = 20 content tokens: `kubectl delete pod <gateway pod> --wait=false [--grace-period N]`. The pod is found from `deploy/inference-gateway` `.spec.selector.matchLabels` (`app.kubernetes.io/instance`, `app.kubernetes.io/name`, `gateway.networking.k8s.io/gateway-name`, all `inference-gateway`). All times are measured from the moment the delete command is issued, so they include kubectl/API/kubelet latency.
- Client: content tokens, how the stream ended, kill → end time.
- Backend: `llamacpp:requests_processing` scraped from the pod IP every 0.5 s for 60 s.
- Recovery: gateway pods polled ~0.5 s for a new Ready pod; pings through the gateway every ~0.5 s on a **fresh connection** each, to **sim-pool** (`max_tokens 1`) so they never hold a llama.cpp slot. Stops at the first 200 after the new pod is Ready.

The gateway Deployment has `terminationGracePeriodSeconds: 60` and readinessProbe `/healthz/ready` every 10 s (`kubectl -n inference get deploy inference-gateway -o yaml`), so a plain delete is a **graceful drain**. Two series were run: the pod's default grace (60 s) and `--grace-period 1` (SIGKILL ~1 s after SIGTERM).

**Evidence (2026-10-13 UTC; raw: `benchmarks/results/probes/p7/20261012-214251.jsonl` (graceful), `…/20261012-214623.jsonl` (`--grace-period 1`)).**

| Run | Grace | Client end | Tokens before end (20 at kill) | Kill → client end | Slot freed after kill | New pod Ready | Failed pings | First 200 after Ready |
|---|---|---|---|---|---|---|---|---|
| 1 | 60 s (default) | normal: `[DONE]`, `finish_reason length` | 1900 | 41.86 s | 42.22 s (stream finished) | 2.66 s | 0 / 4 | 2.66 s |
| 2 | 60 s (default) | normal: `[DONE]`, `finish_reason length` | 1900 | 42.87 s | 43.23 s (stream finished) | 2.51 s | 0 / 4 | 2.51 s |
| 3 | 60 s (default) | normal: `[DONE]`, `finish_reason length` | 1900 | 41.54 s | 41.71 s (stream finished) | 3.31 s | 0 / 5 | 3.31 s |
| 1 | 1 s | `httpx.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)` | 145 | 2.20 s | 2.52 s | 2.73 s | 2 / 6 (`ConnectError` at 2.73, 3.24 s) | 3.75 s |
| 2 | 1 s | same `RemoteProtocolError` | 137 | 2.20 s | 2.52 s | 2.44 s | 2 / 6 (`ConnectError` at 2.44, 2.95 s) | 3.46 s |
| 3 | 1 s | same `RemoteProtocolError` | 138 | 2.19 s | 2.51 s | 3.09 s | 2 / 6 (`ConnectError` at 2.42, 3.09 s) | 3.60 s |

In every run `requests_processing` was 1 at the first sample after the kill. The first graceful series' console summary printed "processing at kill 0.0 / slot NOT freed": that was a probe bug (it used the last sample *before* the kill, taken before the request reached the engine). It was fixed and the graceful rows above were recomputed from the raw samples in the jsonl, which were unaffected. The hard-kill series ran with the fixed probe.

**What it means.**
- **Graceful delete (rollout, eviction, node drain): no client impact here.** The terminating pod finished a 42 s stream inside its 60 s grace period, and new connections kept getting 200s while the replacement started. A stream longer than the grace period would be cut at 60 s (not tested).
- **Hard kill (OOM kill, crash, SIGKILL after grace): the stream is lost.** The client gets a protocol error about 2.2 s after the delete is issued, after ~120 more tokens. The **engine slot is freed** ~0.3 s later: when the gateway process dies its upstream socket closes, llama.cpp's next write fails and it cancels. That is the opposite of P3, where a *downstream* close is not passed upstream while the gateway lives.
- **Recovery** took 2.4–3.3 s to a new Ready pod. With 1 replica there was a window of refused connections (2 failed pings per run; first failure → first 200: 1.02 / 1.02 / 1.18 s), and the first 200 came 3.5–3.8 s after the delete.
- **An in-flight stream can't be resumed.** There is no resume protocol across OpenAI-style SSE: a client retry regenerates the whole response from the prompt and spends the prefill + decode compute twice (here, the ~140 tokens already generated are thrown away).
- **More gateway replicas (#19) are not HA on this lab.** Two agentgateway replicas would remove the refused-connection window for a single pod kill, and a client retry would land on the survivor. But both replicas run on the one node `ravi-home`: the node, k3s ServiceLB and the LB IP are still a single point of failure. And replicas don't save the stream on the pod that died.

**Rerun with 2 gateway replicas (2026-10-14, #20).** The chart now renders an `AgentgatewayParameters` (`gateway.proxy` in
`deploy/charts/inference/values*.yaml`; `values-k3s.yaml`: `replicas: 2`) referenced from the Gateway's `spec.infrastructure.parametersRef`:
Deployment `replicas: 2`, soft pod anti-affinity on `kubernetes.io/hostname`, and a PodDisruptionBudget `minAvailable: 1`
(`kubectl -n inference get deploy inference-gateway` → 2/2; `get pdb` → MIN AVAILABLE 1, ALLOWED DISRUPTIONS 1).
`scripts/probe_p7_gateway_kill.py` was extended for N replicas: it deletes only the pod that accepted the stream's
connection (the one whose `agentgateway_downstream_connections_total` grew when the stream started; `--target all` = old
behaviour) and `--ping-window 10` keeps pinging (fresh connection each, sim-pool, `max_tokens 1`) for ≥ 10 s.
Command: `.venv/bin/python scripts/probe_p7_gateway_kill.py --grace-period 1 --runs 3 --ping-window 10 --out-dir observability/evidence/p7`
(raw: `observability/evidence/p7/20261014-225149.jsonl`).

| Run | Client end (stream on the killed pod) | Tokens (20 at kill) | Kill → client end | Slot freed after kill | Replacement Ready | Pings (0–10 s after kill) | Failed |
|---|---|---|---|---|---|---|---|
| 1 | `RemoteProtocolError` (incomplete chunked read) | 199 | 2.2 s | 2.52 s | 2.98 s | 17 × 200 | 0 |
| 2 | same | 186 | 2.2 s | 2.52 s | 2.81 s | 18 × 200 | 0 |
| 3 | same | 213 | 2.2 s | 2.51 s | 3.81 s | 16 × 200 | 0 |

An earlier series the same day (`…/20261014-224832.jsonl`, 20/19/20 pings, 0 failed, same stream outcome) counted the
*survivor* as the "new pod" (probe bug, fixed before the series above), so its "Ready" times are not replacement times.

- **New requests kept succeeding**: 0 failed pings in every run, first 200 at 0.19 s after the delete (the survivor),
  versus 2 failed pings per run and first 200 at 3.5–3.8 s with one replica.
- **The in-flight stream on the killed pod is still lost**, exactly as with one replica: protocol error 2.2 s after the
  delete, ~170 tokens thrown away, slot freed ~0.3 s later. Replicas do not make a stream survive its pod; there is no
  resume for OpenAI-style SSE, so a client retry regenerates from the prompt.
- **This is still not HA.** Both replicas run on the single node `ravi-home` (soft anti-affinity has nowhere else to
  go): the node, k3s ServiceLB and the LB IP 192.168.117.204 remain a single point of failure (#19).

**Mitigation.** Done here: gateway replicas = 2 + PodDisruptionBudget (#20) removes the refused-connection window of a single pod kill. Keep a grace period longer than the longest legitimate stream so rollouts drain. Clients retry on connection errors and on truncated streams (no `[DONE]` / no `finish_reason`) and accept that the retry pays the full compute again. Real HA needs ≥ 2 nodes.

---

## P9 — Burst inside one EPP metrics refresh (#22)

(P8 is unassigned.)

**Question.** The EPP scores pods on scraped metrics. If N requests reach it faster than it refreshes those metrics, are they all scored against the same snapshot and herded onto one pod?

**Refresh interval in our deployment.** `--refresh-metrics-interval` = **50 ms**. Sources:
- Our EPP Deployment args (`kubectl -n inference get deploy sim-pool-epp -o jsonpath='{...args}'`) don't set it. The `sim-pool-epp` ConfigMap (`default-plugins.yaml`) has no interval parameter on `metrics-data-source`.
- The EPP's own startup log line `"msg":"Flags processed"` (`kubectl -n inference logs deploy/sim-pool-epp`) shows the effective value: `"refresh-metrics-interval":50000000` (ns = 50 ms), `"metrics-staleness-threshold":2000000000` (2 s), `"refresh-prometheus-metrics-interval":5000000000` (5 s, the EPP's own Prometheus flush, not backend scraping).
- `podman run --rm ghcr.io/llm-d/llm-d-router-endpoint-picker:v0.9.0 --help`: `--refresh-metrics-interval duration  Interval to refresh metrics. (default 50ms)`.

So we run the default. That this flag also drives the `metrics-data-source` plugin's scrape loop is inferred from the flag text, not verified in the source.

**Method.** `scripts/probe_burst.py` (`make probe-burst`), sim-pool, 2 pods × max-num-seqs 2. Each run starts from idle (both pods running 0 / waiting 0). N = 8 requests through the gateway, unique prompts (neutralises the prefix-cache scorer), `ignore_eos`, `max_tokens 200`, so every request lasts longer than the whole send window and all 8 overlap in both modes.
- **burst**: all 8 fired at once (`asyncio.gather`).
- **spaced** (control): one every 0.25 s (5 × the refresh interval).

Modes alternate within each repeat. **Which pod**: the gateway access log `endpoint=` per request (the gateway start time = log timestamp − `duration`, which gives the spread as the gateway saw it), cross-checked against per-pod deltas of `vllm:e2e_request_latency_seconds_count` scraped from each pod IP. The two agreed in all 26 runs below. There is no response header naming the endpoint.

**Evidence (SIMULATED, 2026-10-13 UTC; raw: `benchmarks/results/probes/burst/20261012-215229.jsonl` (3 repeats), `…/20261012-215340.jsonl` (10 repeats)).** Pods: A = `10.42.0.35`, B = `10.42.0.5`.

| Mode | Runs | Send spread at the gateway | Per-run split A/B | Most-loaded pod got | Total A / B |
|---|---|---|---|---|---|
| burst | 13 | 0.5–7.7 ms (≪ 50 ms) | 3/5, 7/1, 3/5, 4/4, 4/4, 3/5, 4/4, 2/6, 6/2, 4/4, 5/3, 4/4, 4/4 | 4 ×6, 5 ×4, 6 ×2, 7 ×1, 8 ×0 | 53 / 51 |
| spaced (control) | 13 | 1756.3–1759.9 ms | 4/4 in all 13 | 4 ×13 | 52 / 52 |

All 208 requests returned 200. Worst burst run (3-repeat series, #2): 0.3 s after sending, A read running 2 / **waiting 5** while B read running **1** / waiting 0. One request queued on A behind 4 others while B had a free slot. A trial run before the log parser was fixed showed the same 7/1 burst split by counter delta (log picks unusable, file not kept).

**What it means (SIMULATED).**
- **No full herding.** A burst inside one refresh never sent all 8 to one pod, so the EPP doesn't pick the same pod deterministically from a stale snapshot. Totals over 13 bursts are balanced.
- **But burst balance is luck, spaced balance is load-aware.** Spaced requests were split 4/4 every time, because each pick saw the previous ones in the scraped `running`/`waiting`. Burst splits scattered from 4/4 to 7/1. That is consistent with every burst request getting the same scores and the picker breaking ties randomly, which the probe can't prove (no per-request scores logged). The cost is a queue on one pod while the other has free slots.
- At 2 pods × 2 slots the damage is bounded. With more pods and larger bursts (agent fan-out, batch clients), a stale snapshot with random tie-breaks leaves capacity idle in the same way. The sim's timing is synthetic, but the routing decisions are real EPP behaviour.

**Next.** (a) EPP verbosity up (`-v`) to log per-request scores and confirm ties. (b) Repeat with in-flight accounting, if the EPP has a plugin that counts requests it has routed but not yet seen in metrics (not checked). (c) Larger N and a shorter refresh (e.g. `--refresh-metrics-interval 10ms`) to see whether the spread changes. (d) llamacpp-pool once it has ≥ 2 replicas.

**Side observation.** Gateway responses carry `x-went-into-resp-headers: true` (`curl -D -` through the gateway to sim-pool). It looks like a debug header from the response-headers path and is visible to clients. Source not checked.

---

## Gateway smoke and #13 (2026-10-12)

**#13: `usage` in the final stream chunk via the gateway (llamacpp-pool).** `curl -sSN http://192.168.117.204/v1/chat/completions -H 'x-pool: cpu'` with `stream: true`, `max_tokens 16`, `stream_options: {"include_usage": true}` → HTTP 200, 13 `data:` lines. Last 2 chunks:

```
data: {"choices":[],"created":1791855606,"id":"chatcmpl-brf3AbQEYoNnujFFWYc6u3qEpWEWIyzb","model":"qwen2.5-0.5b-instruct","system_fingerprint":"b11146-7fe450e19","object":"chat.completion.chunk","usage":{"completion_tokens":10,"prompt_tokens":34,"total_tokens":44,"prompt_tokens_details":{"cached_tokens":24}},"timings":{"cache_n":24,"prompt_n":10,"prompt_ms":515.418,"prompt_per_token_ms":51.5418,"prompt_per_second":19.401728305957494,"predicted_n":10,"predicted_ms":161.151,"predicted_per_token_ms":17.90566666666667,"predicted_per_second":55.84824171119013}}
data: [DONE]
```

Yes: the last data chunk has `choices: []` and `usage`; agentgateway passes it through unchanged.

**`scripts/smoke_test.py --runs 10`** (OpenAI SDK, non-stream + stream with usage):

| Pool | TTFT p50 / max | total p50 / max | runs without usage |
|---|---|---|---|
| sim-pool (default route), **SIMULATED** | 44.1 / 52.7 ms | 484.8 / 546.5 ms | 0 |
| llamacpp-pool (`--pool cpu`) | 61.2 / 65.5 ms | 600.6 / 618.5 ms | 0 |

Model file in the llama.cpp pod (`kubectl exec <pod> -- ls -l /models/*.gguf`): `qwen2.5-0.5b-instruct-q4_k_m.gguf`, 491400032 bytes.

`helm test inf` (2026-10-12 21:40 EDT): `inf-gateway-sanity-test`, `inf-llamacpp-sanity-test`, `inf-vllm-sim-sanity-test` all Succeeded. `helm history inf`: rev 30 deployed (2026-10-05 15:55:50), revs 21–29 superseded.

---

## How to reproduce

```bash
.venv/bin/python scripts/probe_p1_saturation.py                 # P1 saturated
.venv/bin/python scripts/probe_p1_saturation.py --no-saturate   # P1 control (refuses unless A idle)
.venv/bin/python scripts/probe_p2_failopen.py --n 50             # P2 (scales sim-pool-epp 0 → 1)
.venv/bin/python scripts/probe_p3_disconnect.py                 # P3 via gateway
.venv/bin/python scripts/probe_p3_disconnect.py --direct        # P3 direct to pod
.venv/bin/python scripts/probe_p3_disconnect.py --backend sim [--direct]   # P3 on the simulator (SIMULATED)
make probe-p7                                                   # P7: deletes the gateway pod mid-stream, 3 runs (graceful)
make probe-p7 ARGS="--grace-period 1"                            # P7 hard kill
make probe-burst                                                # P9: 3 × (burst of 8, spaced control), SIMULATED
scripts/probe_epp_scrape.sh                                     # llamacpp-pool: EPP vs engine queue
```

All need `kubectl` access to ns `inference` and the gateway LB reachable from the host.

## Untested

- EPP **hung** (accepts, never answers): gateway timeout and fail-open behaviour.
- HTTPRoute `timeouts.request` as a disconnect bound; its effect on long streams.
- Disconnect propagation with HTTP/2 clients (only HTTP/1.1 via httpx tested).
- Sim disconnect behaviour in newer sim releases (only v0.10.2 tested).
- P1 on llamacpp-pool with 2+ replicas (only 1 replica today); balance quality at moderate load.
- BBR on agentgateway.
- EPP Flow Control enabled.
- TLS on :443 (no cert; #17).
- P7: a stream longer than the gateway's 60 s grace period; HTTP/2 clients; which pod served the pings during a graceful drain; a graceful (default-grace) delete with 2 replicas.
