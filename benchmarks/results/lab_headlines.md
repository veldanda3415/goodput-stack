## Lab results (k3s / k3d on the workstation)

Hand-curated: one row per headline lab finding, each linking the write-up that has the method, raw files and caveats.
Labels: **SIMULATED** = llm-d-inference-sim (vLLM API and metrics, no model: routing, scaling and scheduling decisions are
real, latencies are configured); **workstation CPU** = real llama.cpp on an i7-10700 (single node); **SIMULATED GPUs** =
Run:ai fake-gpu-operator (the scheduler sees devices that don't exist); **EMULATED** = containerlab veth links + Linux
kernel forwarding (FRR control plane is real; throughput is never switch or NIC performance); **SOFT-ROCE** = `rdma_rxe` in QEMU
guest kernels (CPU-bound, no DCQCN); **OFFLINE-VALIDATED** = checked by Batfish, never deployed; **CALCULATED** = design
arithmetic from cited datasheets, nothing run. Small n: these are behaviour checks, not benchmarks.
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
| fabric | F1 bring-up: 2 spines × 4 leaves, eBGP unnumbered (IPv4 over IPv6 next hops), BFD, rendered from one intent file | 16 / 16 sessions Established ≈ 5.6 s after deploy start; two-way ECMP on every leaf | EMULATED | [f1-bringup](fabric/results/f1-bringup.md) |
| fabric | E1 ECMP hash: L3 vs L4 policy, 1 / 4 / 32 flows (leaf TX-byte counters, 3 repeats) | L3: 100 % on one uplink at every flow count; L4 32 flows: 37–53 % / 47–63 % | EMULATED | [E1](fabric/experiments/E1-ecmp-hash.md) |
| fabric | E2 BFD under silent loss (carrier stays up) | loss window 488–568 ms with BFD vs 7.4–9.1 s without (3 repeats each) | EMULATED | [E2](fabric/experiments/E2-bfd-convergence.md) |
| fabric | E3 RDMA RC across a spine (VM endpoints; container rxe blocked by the kernel, #31) | `ib_write_bw` 0.60–0.64 Gbit/s; RoCE v2 on UDP 4791 with DSCP 26 on the wire | SOFT-ROCE + EMULATED | [E3](fabric/experiments/E3-soft-roce.md) |
| fabric | E4 RED/ECN on a 500 Mbit/s bottleneck | TCP ECN: CE marks + ECE/CWR response; Soft-RoCE: RED marked counter +11,615, zero CNPs (rxe has no DCQCN) | EMULATED | [E4](fabric/experiments/E4-ecn.md) |
| fabric | E5 collective traffic vs ECMP, uplinks shaped to 500 Mbit/s, 36 runs | job time tracks the busiest link (Pearson r = 0.998); ring with L3 hash ≈ 1.9× the measured even split; L4 + 16 flows/pair within +0.03 s | EMULATED | [E5 shaped](fabric/experiments/E5-collective-entropy.md#shaped-uplinks-rerun) |
| fabric | E6 failure drills under a shaped ring collective | silent loss: 0.5–0.7 s loss (BFD); a 2 s flap every 20 s cost > 30 s of step time vs ≈ 8 s for a dead link; one leaf down stalled the whole ring | EMULATED | [E6](fabric/experiments/E6-failure-drills.md) |
| fabric | E7 EVPN-VXLAN front-end tenants (2 VRFs, symmetric IRB) | 8 / 8 same-tenant pairs reach, 12 / 12 cross-tenant and 15 / 15 tenant→rail blocked; route-target and next-hop traps reproduced | EMULATED | [E7](fabric/experiments/E7-evpn-tenancy.md) |
| fabric | NX-OS render + Batfish pre-deploy check (numbered variant; lab's unnumbered FRR also checked) | 16 / 16 sessions compatible; a one-device ASN drift flagged as 4 half-open sessions before deploy | OFFLINE-VALIDATED | [batfish/](fabric/batfish/README.md), [ADR 0006](docs/adr/0006-multi-nos-render-batfish.md) |
| fabric | One link at 50 % in the inter-node ring, 8B model on 256 GPUs | DP all-reduce +55 %, step +8.3 % | CALCULATED | [DESIGN §2](fabric/DESIGN.md) |
