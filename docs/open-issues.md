# Open issues and gaps

Issue numbers used across this repo (`#19`, `#26`, `#32`, ...) refer to this log, not to GitHub issues or PRs.
One row per issue; open issues first (newest first), closed issues at the bottom. Labels follow the
[README](../README.md#ground-rules): SIMULATED (vLLM simulator / fake GPUs), EMULATED (containerlab), SOFT-ROCE, real (Kaggle T4).

## Open

| # | Opened | Issue | Status | Evidence / next step |
|---|---|---|---|---|
| 32 | 2026-10-16 | Fabric failure drills: the largest losses came **after repair**, not at failure (spine restore: 1.0–2.7 s of loss ≈ 4 s after link-up) | Open. H1 refuted, H2 untested | EMULATED. H1 (BGP advertises the spine before its FIB is ready, fix with `update-delay`) is **refuted**: zebra re-adds the restored spine to the leaves' kernel ECMP group at link-up while BGP is still Idle; loss opens when the leaf resolves the spine's link-local and closes when the spine's FIB is installed. `update-delay` only acts on bgpd restart. H2: test a nexthop-group / link-up hold-down. [E6](../fabric/experiments/) |
| 31 | 2026-10-15 | Soft-RoCE cannot send from a container network namespace: kernel 6.18 `rdma_rxe` does its route lookup and opens UDP 4791 only in the initial netns (`rxe_net.c`) | Worked around; root limitation open | RDMA endpoints run as two QEMU/KVM VMs attached to leaf ports (each guest runs rxe in its own init netns): RoCE v2 GID ACTIVE, `ib_write_bw` cross-spine. Close if no container path is needed |
| 30 | 2026-10-15 | `token-load-scorer` limits: in-flight token state is per EPP replica and in memory; load not dispatched by this EPP is invisible; a request that never yields a first token holds its tokens until the 5-min janitor; tokens estimated as bytes/4 | Open (design limits, documented) | [ADR 0003](adr/0003-token-aware-scorer.md), [GAPS P8](../deploy/gateway/GAPS.md). Paths: engine-reported queued tokens, shared state across EPP replicas, real token counts, shorter janitor TTL |
| 28 | 2026-10-14 | Missing metrics: EPP v0.9.0 has no decision-latency metric; agentgateway has no gateway-side TTFT (its duration histogram ends at end of stream); llama.cpp has no latency histograms | Open. Upstream draft written, not filed | [docs/upstream/](upstream/). TTFT today = client-side or the vLLM engine histogram |
| 27 | 2026-10-14 | Summing per-pod gauges over-counts: pods are scraped at different instants, so `sum()` of in-flight gauges exceeds true load → spurious scale-up | Mitigated | `avg_over_time(...[30s])` + replica cap. Better: one pool-level metric from a single source (EPP / gateway queue). [autoscaling/](../autoscaling/) |
| 26 | 2026-10-14 | agentgateway cancels the ext_proc (EPP) call at 10.0 s and the policy has no timeout field → with EPP flow control holding requests at 0 replicas, a request still held at 10 s gets HTTP 500 | Open. Upstream draft written, not filed | Blocks scale-from-zero for backends that take > ~5 s to start (llama.cpp cold load, GPU pods). [Draft](upstream/agentgateway-extproc-timeout.md) |
| 24 | 2026-10-12 | Gateway responses carry `x-went-into-resp-headers: true`, visible to clients | Open | Find which component sets it; strip at the gateway if it is a debug header |
| 22 | 2026-10-06 | The EPP decides on metrics as of the last refresh; a burst inside one refresh can skew | Mechanism answered; open for larger n | SIMULATED. Stock profile: all burst requests got identical queue scores → random tie-break (splits up to 6/2). With `token-load-scorer` the in-flight counter updates inside the burst → mostly 4/4. A dispatch-time counter beats scraped metrics for bursts |
| 21 | 2026-10-06 | Gateway / EPP capacity limit not measured | Overhead measured; limit open | SIMULATED, quiet host, 3 runs: at ≤ 16 concurrent the gateway costs −2.7 to −4.7 % rps and +4–11 ms p50 vs direct. Above 16 the single load generator saturates first, so higher numbers are not quotable. Next: multi-process / separate-host client |
| 20 | 2026-10-06 | Single-node gateway is a SPOF; in-flight streams are lost on hard gateway death | Mitigated; residual open | 2 replicas + PDB + anti-affinity: hard kill → 0 failed new requests, the stream on the killed pod is still lost. Residual: node SPOF; streams cannot be resumed |
| 19 | 2026-10-05 | A client disconnect through agentgateway does not free the engine slot: direct, llama.cpp cancels a streaming request in ~1.5 s; through the gateway the slot stays busy ≥ 15 s | Open | [GAPS P3](../deploy/gateway/GAPS.md), `scripts/probe_p3_disconnect.py`. agentgateway v1.6.0 has request / backend / idle timeouts but no disconnect-propagation setting found. Also leaks `token-load-scorer` counters (#30) |
| 16 | 2026-10-04 | The gateway sees client source 10.42.0.1: ServiceLB + `externalTrafficPolicy: Cluster` SNATs the client IP | Open (needed before per-client rate limits) | `externalTrafficPolicy: Local` on the gateway Service |
| 15 | 2026-10-04 | llama.cpp is not a built-in EPP engine | Config path done; upstream PR planned | `engineConfigs` entry + pod label work. llama.cpp exports no KV usage or slot count, so the KV scorer adds nothing for llamacpp-pool (GAPS P4) |
| 12 | 2026-10-02 | The harness's model of the simulator's load factor is wrong for 1 client + long prompts (+78–87 %) | Open | Read the simulator's under-load time factor |
| 11 | 2026-10-02 | Same model on two pools → config must be model → [pools with properties], not model → Service | Open (design in GAPS P5) | Today the pool is chosen by header (`x-pool: cpu`). Options: client header, body-based routing, EPP filter; evaluate upstream `context-length-aware` |
| 10 | 2026-10-02 | Scale-from-zero returned errors while no pod existed | Solved for fast-start backends; open for slow-start (#26) | EPP flow control holds requests at 0 endpoints while KEDA scales: 0/5 errors, first token 4.5–4.8 s (SIMULATED, 3 runs) |
| 9 | 2026-10-02 | NetworkPolicy programming race: a new source pod's first connection is refused (< 1 s window) | Open | Not seen on long-lived gateway pods |
| 8 | 2026-10-02 | Zero-error pod delete depends on preStop sleep > new pod's time to serving; long streams can be cut after the grace period | Open | Tie preStop / grace period to measured bring-up; graceful drain for long streams |
| 7 | 2026-10-02 | Readiness period 5 s adds a random 0–5 s between model loaded and Ready | Open (decide) | Readiness 2 s (more probe load) or accept |
| 6 | 2026-10-01 | Chart hardening | Mostly done | Remaining: init-container download timeout |
| 5 | 2026-10-01 | PVC is local-path RWO, shared by all replicas → replicas on another node would be Pending | Open (multi-node) | Fine on one node (KEDA scaled llama.cpp to 3 replicas) |
| 3 | 2026-09-28 | Where TTFT / ITL is measured: engine, gateway and client disagree | Partly answered | The simulator's TTFT histogram excludes queue wait (engine p95 ≤ 86 ms vs client p50 1.54 s under queueing). The dashboard shows engine TTFT and queue time side by side |
| 1 | 2026-09-28 | Benchmarks must defeat prefix caching and count chat-template tokens in input size | Open | Probes use unique prompts + `cache_prompt: false`; identical prompts let the prefix scorer mask queue-based routing (P1) |

## Closed

| # | Opened | Issue | Closed | Resolution |
|---|---|---|---|---|
| 23 | 2026-10-06 | Routing is size-blind: queue length counts requests, not prompt tokens | 2026-10-15 | Proven (P8 stock: 8/8 to the long-prompt pod, TTFT p50 7.75 s), then fixed by configuration: llm-d's `token-load-scorer` is inert at its default threshold; threshold 8192, weight 4 → 0/8, TTFT p50 0.56 s. No custom plugin (it would duplicate upstream). [ADR 0003](adr/0003-token-aware-scorer.md); residual limits → #30 |
| 29 | 2026-10-14 | Helm and the HPA both owned `spec.replicas` (sim went 2 → 1 on upgrade) | 2026-10-14 | Chart value `<backend>.autoscaled` omits `replicas` when KEDA owns it |
| 25 | 2026-10-12 | Contributor docs still described a custom FastAPI router | 2026-10-13 | Docs aligned with the integrated gateway (agentgateway + Inference Extension + llm-d EPP) |
| 18 | 2026-10-04 | Not verified that the EPP scrapes pool pods' `/metrics` | 2026-10-05 | Verified on both pools (P1: saturated pod behind the gateway's back got 0 / 20) |
| 17 | 2026-10-04 | https:443 listener with no TLS certificate | 2026-10-05 | Removed from lab values ([ADR 0002](adr/0002-gateway-in-chart.md)) |
| 14 | 2026-10-02 | WSL2 stock kernel has no Soft-RoCE | 2026-10-02 | Out-of-tree `rdma_rxe.ko` built against the stock kernel source, loaded at boot |
| 13 | 2026-10-02 | Token usage in streams on both backends | 2026-10-12 | Usage arrives in the final chunk through the gateway on both pools |
| 2 | 2026-09-28 | Pin backend port / host; decide on a backend API key | 2026-10-02 | Auth at the gateway; backends protected by NetworkPolicy |
