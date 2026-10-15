# ADR 0005 — Rail-optimized leaf-spine for the scale-out backend

- **Status:** accepted for this design (2026-10-15). It is a design decision
  backed by CALCULATED sizing. Nothing here was built or measured on hardware.

## Context

The AI-fabric track needs one backend (compute fabric) topology for the
reference design in [`fabric/DESIGN.md`](../../fabric/DESIGN.md). The
reference node has 8 GPUs and 8 × 400G NICs, one per GPU (S1 in
[`fabric/design/sources.md`](../../fabric/design/sources.md)). The target
sizes are 256 and 2,048 GPUs, and the switches are 51.2 Tb/s class (S6–S8).

The traffic model in DESIGN.md §2 (CALCULATED) shows that when TP stays
inside a node, data-parallel and pipeline-parallel traffic run between
same-index GPUs on different nodes. That traffic is rail-aligned. The
remaining cross-rail traffic is mainly MoE all-to-all. Flows are few and run
at line rate, which makes ECMP hashing unreliable (S12; the F1 lab's E1 shows
the same effect in Linux kernel hashing, EMULATED).

## Decision

Use a **rail-optimized, non-blocking 2-tier leaf-spine** backend, as in the
DGX SuperPOD (S9, S10). NIC *r* of every node connects to rail *r*'s leaves,
and all leaves connect to a common spine layer. 51.2T switches run as
128 × 400G (S6, S7). CALCULATED counts (`python -m fabric.design.sizing`):

| GPUs | Leaves | Spines | Switch–switch links | Optical transceivers | Same-rail pairs at 1 hop |
|---:|---:|---:|---:|---:|---:|
| 256 | 8 | 2 | 256 | 1,024 | 100 % |
| 2,048 | 32 | 16 | 2,048 | 8,192 | 25 % |

The 2-tier ceiling is k²/2 = 8,192 GPUs at k = 128. The same code reproduces
S9's published SuperPOD leaf and spine counts at k = 64. The F1 lab is a
2-rail miniature of this decision and uses the same eBGP design
([ADR 0004](0004-fabric-intent-render.md)).

## Alternatives and when to pick them

- **Plain leaf-spine (leaf per rack).** At 256 GPUs it uses the same switch
  count (8 leaves, 2 spines; CALCULATED). NIC links are in-rack, so they can
  be copper (≤ 3 m, S19), which halves the transceivers. Only 10 % of
  same-rail pairs are one hop apart, so most collective bytes cross the spine
  and depend on ECMP. *Pick it* for mixed or general-purpose clusters, for
  inference fleets where requests stay within one node, or when optics cost
  or power is the binding constraint.
- **Rail-only (no spine; Wang et al., S11).** This removes the spine and
  sends cross-rail traffic over NVLink. The paper claims 38–77 % lower network
  cost (its own study). CALCULATED here: at 256 GPUs it saves both spines and
  half the transceivers. At 2,048 GPUs each rail needs its own leaf-spine, and
  the count matches rail-optimized. *Pick it* when every rail fits one switch
  (≤ k nodes, here ≤ 1,024 GPUs), the workload is dense TP×DP×PP training with
  little all-to-all, and the cluster is not shared by jobs with arbitrary
  placement.
- **Dragonfly (Kim et al., S20).** Groups of switches act as one virtual
  high-radix router, with few long global links. The abstract reports a lower
  cost than a folded Clos at ≥ 16K nodes. It depends on adaptive routing and
  is not full-bisection for adversarial patterns. *Pick it* at very large
  scale (well past the 3-tier Clos sizes here), where long-cable cost
  dominates and the switches support adaptive routing.
- **InfiniBand fat-tree (QM9700, S8; SuperPOD, S9).** This is the same
  rail-optimized Clos on InfiniBand. It gives credit-based lossless transport,
  subnet-manager routing and adaptive routing out of the box, but radix 64 at
  400G puts the 2-tier ceiling at 2,048 GPUs. *Pick it* when the team wants
  the vendor-validated stack (SuperPOD) and the cluster is single-tenant
  training. This repository targets Ethernet/RoCE v2, so that the same
  operational tools (BGP, FRR, intent rendering; ADR 0004) cover front-end and
  backend.
- **3-tier Clos.** This is required past k²/2 GPUs. Llama 3 used full
  bisection within 3,072-GPU pods and 1:7 between pods (S13). *Pick it*
  beyond the 2-tier ceiling, oversubscribing above the pod only if the
  scheduler keeps jobs inside pods.

## Consequences

- Every NIC link is optical (the leaves serve 32–64 nodes across racks), so
  there are 1,024 transceivers at 256 GPUs vs 512 for plain leaf-spine
  (CALCULATED).
- Rail-aligned placement is now the scheduler's job. A job placed with TP
  across nodes loses the benefit.
- Cross-rail and MoE all-to-all traffic still crosses the spine and needs the
  entropy and congestion measures planned for F3/F4.
- 800G NICs on 64 × 800G switches cut the 2-tier ceiling to 2,048 GPUs
  (CALCULATED; DESIGN.md §3.3). Revisit this ADR at that hardware generation.
