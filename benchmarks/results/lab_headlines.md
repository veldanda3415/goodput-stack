## Lab results (k3s / k3d on the workstation)

Hand-curated: one row per headline lab finding, each linking the write-up that has the method, raw files and caveats.
Labels: **SIMULATED** = llm-d-inference-sim (vLLM API and metrics, no model: routing, scaling and scheduling decisions are
real, latencies are configured); **workstation CPU** = real llama.cpp on an i7-10700 (single node); **SIMULATED GPUs** =
Run:ai fake-gpu-operator (the scheduler sees devices that don't exist). Small n: these are behaviour checks, not benchmarks.
Appended to RESULTS.md by `benchmarks/analyze.py` (links are relative to the repo root); edit this file, not RESULTS.md.

| area | result | value | label | write-up |
|---|---|---|---|---|
| gateway | P1 load-aware routing: one sim pod saturated behind the gateway's back | 20 / 20 requests to the idle pod (idle control 9 / 11) | SIMULATED | [GAPS.md P1](deploy/gateway/GAPS.md#p1--does-the-epp-route-by-load) |
| gateway | P2 EPP scaled to 0 (`failureMode: FailOpen`) | 150 / 150 requests 200; routing falls back to the gateway's load-blind LB; EPP-down alert fires in 36 s | SIMULATED | [GAPS.md P2](deploy/gateway/GAPS.md#p2--what-happens-when-the-epp-is-gone-failuremode-failopen), [observability/](observability/README.md) |
| gateway | P3 client disconnect through agentgateway | engine slot **not** freed within 15 s (direct stream: ~1.5 s) — open gap #19 | workstation CPU | [GAPS.md P3](deploy/gateway/GAPS.md#p3--does-a-client-disconnect-free-the-engine-slot) |
| gateway | P7 gateway pod hard-killed, 2 replicas + PDB | 0 failed new requests; the killed pod's in-flight stream is lost; replacement Ready 2.8–3.8 s | workstation CPU | [GAPS.md P7](deploy/gateway/GAPS.md) |
| gateway | P8 size-blind routing: few long vs many short prompts, stock EPP | 8 / 8 probes to the long-prompt pod, TTFT p50 7.75 s (predicted ~7.7 s) vs 0.53 s on the other pod | SIMULATED | [GAPS.md P8](deploy/gateway/GAPS.md#p8--is-the-epp-size-blind-23) |
| gateway | P8 with upstream `token-load-scorer` tuned (threshold 8192, weight 4) | 0 / 8 to the long-prompt pod, TTFT p50 0.56 s; P1 still 20 / 20; scheduler 0.032 → 0.112 ms, client p50 change within noise | SIMULATED | [GAPS.md P8](deploy/gateway/GAPS.md#p8--is-the-epp-size-blind-23), [ADR 0003](docs/adr/0003-token-aware-scorer.md) |
| gateway | P9 burst of 8 inside one 50 ms EPP refresh | never 8 / 0; splits 4/4 … 7/1 (random tie-break); spaced control 4/4 every run | SIMULATED | [GAPS.md P9](deploy/gateway/GAPS.md#p9--burst-inside-one-epp-metrics-refresh-22) |
| autoscaling | KEDA on queue depth, sim-pool, one cycle | 1 → 3 → 4 → 1 replicas; 1144 / 1144 ok; client TTFT p50 2,710 ms (1 replica) → 81–93 ms (4) | SIMULATED, n = 1 | [autoscaling/](autoscaling/README.md#one-full-cycle-per-pool-loadgenpy) |
| autoscaling | KEDA on queue depth, llamacpp-pool, one cycle | 1 → 3 → 1 replicas; 206 / 206 ok; client TTFT p50 3.6–4.6 s → 0.57–0.84 s | workstation CPU, n = 1 | [autoscaling/](autoscaling/README.md#one-full-cycle-per-pool-loadgenpy) |
| autoscaling | Scale-from-zero via EPP flow control + KEDA | 0 / 5 errors in each of 4 runs, first token 4.5–7.2 s; flow control off: 5 / 5 immediate 503; held requests cut at 10 s by agentgateway (#26) | SIMULATED | [autoscaling/](autoscaling/README.md#scale-from-zero-10-gapsmd-p6) |
| observability | Scrape targets (gateway, both EPPs, engines) | 19 / 19 up; agentgateway's duration histogram ends at end of stream (no gateway TTFT); the sim's TTFT excludes queue wait | SIMULATED backends | [observability/](observability/README.md) |
| scheduling | GPU exhaustion on 2 nodes × 2 fake T4s | 4 / 5 pods Running, 5th Pending `Insufficient nvidia.com/gpu` | SIMULATED GPUs | [scenario 01](scheduling/scenarios/01-gpu-exhaustion.md) |
| scheduling | Kueue quotas, borrowing, preemption, gang, TAS | over-quota suspended; cohort borrowing and reclaim; all-or-nothing admission; rack/block placement | SIMULATED GPUs | [scenario 03](scheduling/scenarios/03-kueue-quota-preemption.md) |
| scheduling | GPU node fault (injected XID-style condition) → fence, evict, reschedule | pods Ready on the healthy node in 3.8–6.7 s (3 runs); remediation 0.7 s | SIMULATED GPUs | [scenario 04](scheduling/scenarios/04-gpu-node-health.md) |
| scheduling | Time-slicing | **not demonstrated**: the pinned fake operator doesn't honour it (documented, not faked) | SIMULATED GPUs | [scenario 02](scheduling/scenarios/02-sharing-and-dra.md) |
