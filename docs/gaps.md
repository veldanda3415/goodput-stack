# Gaps

What this project could not do: limits of a CPU-only, single-node workstation plus a free Kaggle T4, and limits in
upstream components that no configuration here can fix. Labels follow the [README](../README.md#ground-rules).

## Fabric, RDMA and RoCE

| Gap | Why it cannot be done here | What exists instead |
|---|---|---|
| Soft-RoCE cannot send from a container network namespace | Kernel 6.18 `rdma_rxe` does its route lookup and opens UDP 4791 only in the initial netns (`rxe_net.c`) | RDMA endpoints run as two QEMU/KVM VMs on leaf ports (rxe in each guest's init netns): RoCE v2 GID ACTIVE, `ib_write_bw` cross-spine. **SOFT-ROCE**, CPU-bound. [E3](../fabric/experiments/E3-soft-roce.md) |
| No lossless RoCE: PFC, DCQCN, switch buffers | veth links have no pause frames, no buffers and no ECN marking in the RoCE path; rxe has no DCQCN | Class mapping and SONiC `config_db` rendered, **INTENT-ONLY**; ECN marking tested with `tc` RED ([E4](../fabric/experiments/E4-ecn.md), [qos/](../fabric/qos/README.md)) |
| No real NICs, switch ASICs or line rate | No RDMA NIC or switch hardware; the fabric is containerlab veth + Linux forwarding | **EMULATED** lab; timings are kernel/FRR, never ASIC ([DESIGN](../fabric/DESIGN.md)) |
| No ASIC hashing, adaptive routing, packet spraying, PHY/FEC/CRC | Vendor ASIC features; veth has no PHY | Linux ECMP hash measured ([E1](../fabric/experiments/E1-ecmp-hash.md)); runbooks marked INTENT-ONLY |
| NX-OS config never deployed | No NX-OS device or image | Rendered from the same intent, **OFFLINE-VALIDATED** by Batfish ([ADR 0006](adr/0006-multi-nos-render-batfish.md)) |
| Scale (256 / 2,048 GPUs), NVLink / scale-up | No hardware at that scale; T4 has no NVLink | **CALCULATED** design from cited datasheets ([DESIGN](../fabric/DESIGN.md), [ADR 0005](adr/0005-backend-topology.md)) |
| Multi-node NCCL: no NIC, RDMA/RoCE or switch in the collective path; ring/tree for N > 2 | Kaggle gives one host with 2 × T4 | 2-GPU NCCL check on one host (SHM, Socket over the VM's own eth0) ([nccl_check](../fabric/design/nccl_check.md)) |

## GPUs and nodes

| Gap | Why it cannot be done here | What exists instead |
|---|---|---|
| GPU scheduling (device plugin, DRA, Kueue, node health) on real GPUs | No local GPU | Separate k3d cluster with **SIMULATED** GPUs ([scheduling/](../scheduling/README.md)) |
| vLLM behind the gateway | vLLM runs on the Kaggle T4 host, which the k3s lab cannot reach | vLLM benchmarked directly on the T4; the gateway fronts the vLLM simulator and llama.cpp |
| Replicas on more than one node | Single-node lab; the PVC is local-path RWO | KEDA scaled llama.cpp to 3 replicas on the one node ([autoscaling](../autoscaling/README.md)) |
| Node-level gateway failover | Single node, so the node is a SPOF | 2 gateway replicas + PDB + anti-affinity: hard pod kill → 0 failed new requests; the stream on the killed pod is still lost ([GAPS P7](../deploy/gateway/GAPS.md#p7--gateway-pod-killed-mid-stream)) |
| Gateway / EPP capacity limit | Above 16 concurrent the single load generator on the same host saturates first | Overhead measured at ≤ 16 concurrent: −2.7 to −4.7 % rps, +4–11 ms p50 vs direct (**SIMULATED**, 3 runs; [GAPS](../deploy/gateway/GAPS.md#disconnect-and-capacity-follow-ups-2026-10-15)) |

## Upstream limits

| Gap | Why it cannot be fixed by configuration | What exists instead |
|---|---|---|
| agentgateway cancels the ext_proc (EPP) call at 10.0 s; the policy has no timeout field | Hard-coded in agentgateway v1.6.0 | Scale-from-zero works for fast-start backends (0/5 errors, **SIMULATED**); blocked for backends that take > ~5 s to start. [Draft upstream issue](upstream/agentgateway-extproc-timeout.md), not filed |
| A client disconnect through agentgateway does not free the engine slot (≥ 15 s busy vs ~1.5 s direct) | agentgateway v1.6.0 has no disconnect-propagation setting | [GAPS P3](../deploy/gateway/GAPS.md#p3--does-a-client-disconnect-free-the-engine-slot), `scripts/probe_p3_disconnect.py`; also leaks `token-load-scorer` counters (row below) |
| No EPP decision-latency metric, no gateway-side TTFT, no llama.cpp latency histograms | Not exported by EPP v0.9.0, agentgateway or llama.cpp | TTFT from the client or the vLLM engine histogram. [Draft upstream issue](upstream/epp-decision-latency-and-gateway-ttft.md), not filed |
| `token-load-scorer`: in-flight token state is per EPP replica and in memory; load not dispatched by this EPP is invisible; tokens estimated as bytes/4 | llm-d plugin design | Documented in [ADR 0003](adr/0003-token-aware-scorer.md) and [GAPS P8](../deploy/gateway/GAPS.md#p8--is-the-epp-size-blind) |
| llama.cpp exports no KV usage or slot count, so the EPP's KV scorer adds nothing for llamacpp-pool | llama.cpp metrics | `engineConfigs` entry + pod label route it; queue + prefix scoring only ([GAPS P4](../deploy/gateway/GAPS.md#p4--llamacpp-exposes-no-kv-cache-or-capacity-signal)) |
