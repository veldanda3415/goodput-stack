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

There is **no KV-cache usage** gauge and **no total-slot** gauge. `n_busy_slots_per_decode` is not a capacity signal: it read `1.61203` while the server was idle (processing 0, deferred 0; `kubectl exec … curl localhost:8080/metrics`, 2026-10-05T19:42Z), so it is an average over past decodes, not the current state. `GET /slots` is enabled (HTTP 200) and returns one object per slot with `n_ctx` (2048 = `-c 4096` / `--parallel 2`) and `is_processing`.

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

## How to reproduce

```bash
.venv/bin/python scripts/probe_p1_saturation.py                 # P1 saturated
.venv/bin/python scripts/probe_p1_saturation.py --no-saturate   # P1 control (refuses unless A idle)
.venv/bin/python scripts/probe_p2_failopen.py --n 50             # P2 (scales sim-pool-epp 0 → 1)
.venv/bin/python scripts/probe_p3_disconnect.py                 # P3 via gateway
.venv/bin/python scripts/probe_p3_disconnect.py --direct        # P3 direct to pod
.venv/bin/python scripts/probe_p3_disconnect.py --backend sim [--direct]   # P3 on the simulator (SIMULATED)
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
