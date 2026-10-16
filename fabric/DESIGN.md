# AI cluster fabric design

This document gives the reasoning behind a production AI-cluster network and
relates it to the EMULATED lab in [`README.md`](README.md). There are three
kinds of number in it, and each is labelled:

- **Cited.** Hardware and model facts, each with an ID (S1, S2, …) that points
  to a row in [`design/sources.md`](design/sources.md) giving the URL and the
  date it was read.
- **Assumption.** An explicit input (A1, A2, …) listed in
  [`design/sources.md`](design/sources.md) with its default and the reason for
  it.
- **CALCULATED.** Output of [`design/collectives.py`](design/collectives.py) or
  [`design/sizing.py`](design/sizing.py) from the inputs in
  [`design/inputs.yaml`](design/inputs.yaml). None of these numbers is a
  measurement. No GPU, NIC or switch hardware was used.

Run `make design-tables` to regenerate every table below (the tables sit
between `design-table` markers). Run `make design-test` for the calculator
tests and the check that the tables are up to date.

The reference node throughout is a DGX H100 (S1): 8 GPUs, 8 single-port
ConnectX-7 NICs at 400 Gb/s for the compute fabric (one per GPU), 2 dual-port
ConnectX-7 cards for storage and in-band traffic, a 1 GbE BMC, and 10.2 kW
maximum. The DGX B200 (S2) keeps the same 8 GPU : 8 NIC : 400G pattern, so the
sizing conclusions carry over.

## 1. The four networks of an AI cluster

NVIDIA's DGX SuperPOD reference architecture (S9, S10) builds four separate
networks. Meta's RoCE training clusters keep the front-end and backend apart
for the same reasons (S12).

| Network | Carries | Reference link speed | Reference switch | Why it is separate |
|---|---|---|---|---|
| **Scale-up** (NVLink/NVSwitch) | Tensor-parallel all-reduces, expert-parallel all-to-all inside a node, and forwarding between rails | 450 GB/s per GPU per direction on H100 (S4; the 900 GB/s figure counts both directions, S3) | NVSwitch inside the node | It has about 9× the per-GPU bandwidth of a 400G NIC (450 GB/s vs 400 Gb/s ÷ 8 = 50 GB/s; CALCULATED) and uses memory semantics. Traffic that fits inside a node should stay there. |
| **Scale-out backend** (compute fabric; RoCE v2 or InfiniBand) | Data-parallel gradient all-reduce, pipeline-parallel sends, cross-node expert traffic, and inference KV-cache transfer | 400 Gb/s per GPU, 8 NICs per node (S1) | 51.2 Tb/s class: SN5600 64×800G / 128×400G (S6), Tomahawk 5 (S7), Quantum-2 QM9700 64×400G (S8) | Few, very large, synchronised flows at line rate (S12). It is non-blocking, lossless or congestion-controlled, and isolated so that other traffic cannot slow a collective. |
| **Front-end** (in-band, north-south) | Job launch, data ingestion, checkpoints, logging (S12), user traffic, and Kubernetes | 2 × 100G bonded per node in the SuperPOD in-band network (S10) | SN4600C 64×100G (S10) | It is bursty and many-to-many, it can be oversubscribed, and it must reach the outside world. |
| **Storage** | Dataset reads and checkpoint writes | ≥ 40 GB/s per node in the SuperPOD (S10) | QM9700 in a separate storage fabric (S10) | It can share the front-end or be its own fabric. The SuperPOD keeps it separate so that checkpoint bursts do not land on the in-band network. |
| **Out-of-band management** | BMC (Redfish/IPMI), switch management ports, and PDUs | 1 GbE (S1) | SN2201 48×1G (S10) | It must keep working when the other three are down or misconfigured. |

The table below gives sizes for the networks other than the backend.
Front-end oversubscription (A10), the front-end minimum spine count (A11) and
one OOB port per switch (A12) are assumptions. Command: `python -m fabric.design.sizing`.

<!-- design-table:other-networks -->
**Front-end, storage and out-of-band networks** — CALCULATED

| GPUs | Nodes | Front-end (in-band) | Storage demand at S10's ≥ 40 GB/s/node | OOB management | Node power, max (kW) |
|---:|---:|---|---|---|---:|
| 256 | 32 | 64 × 100G; 2 leaves, 2 spines (3:1) | 1,280 GB/s (10.24 Tb/s) aggregate | 46 × 1G ports; 1 × 48-port | 326.4 |
| 2,048 | 256 | 512 × 100G; 11 leaves, 4 spines (3:1) | 10,240 GB/s (81.92 Tb/s) aggregate | 319 × 1G ports; 7 × 48-port | 2,611.2 |
<!-- /design-table -->

Storage: at 256 GPUs the aggregate demand of about 10 Tb/s is only one fifth
of the backend's 51.2 Tb/s bisection (§3; both CALCULATED). It is still large enough that
mixing it with collectives on one fabric would need QoS separation, and that
is why S10 gives storage its own fabric. OOB: one or a few 48-port 1G
switches; size it per rack in practice.

## 2. Parallelism → traffic

### 2.1 Models (CALCULATED from the alpha-beta model)

For one collective over *N* ranks on a buffer of *S* bytes per rank, using a
link with effective bandwidth *B* (bytes/s, after efficiency A1/A2) and
per-step latency α (A3/A4):

**Ring all-reduce.** A ring all-reduce is a reduce-scatter followed by an
all-gather. Each phase takes *N − 1* steps, and in each step a rank sends one
chunk of *S/N* bytes. So:

```
bytes on the wire per rank = 2 · (N−1) · S/N = 2(N−1)/N · S
T_ring = 2(N−1)·α + 2(N−1)/N · S / B
```

This matches the nccl-tests bus-bandwidth factor 2(n−1)/n (S15). With N = 2
it gives S; with N = 8 it gives 1.75 S; as N → ∞ it tends to 2S.

**Double binary tree.** The data goes up a tree (reduce) and comes back down
(broadcast), so the depth is ⌈log₂N⌉ each way. NCCL reports that two
complementary trees keep full bandwidth (S16), so only the latency term
changes:

```
T_tree = 2⌈log₂N⌉·α + 2(N−1)/N · S / B
```

At N = 256 the latency term is 16 α instead of 510 α. This matters for small
messages only.

**Reduce-scatter, all-gather and all-to-all** each move (N−1)/N · S per rank
(S15): `T = (N−1)·α + (N−1)/N · S / B`. **Point-to-point**:
`T = α + S / B`.

**Hierarchical all-reduce** (G GPUs per node, M nodes; one rail NIC per GPU):

1. Reduce-scatter inside the node over NVLink: (G−1)/G · S.
2. Ring all-reduce of each GPU's S/G shard across the M nodes, on that GPU's
   own rail: 2(M−1)/M · S/G.
3. All-gather inside the node over NVLink: (G−1)/G · S.

The scale-out bytes per GPU are therefore 1/G of what a flat ring would send.
With G = 8 and M = 4 (S = 800 B), each GPU sends 1,400 B on NVLink and 150 B
on its NIC. This case is a unit test.

**Where each group lands.** The rank layout is TP innermost, then DP, then PP
(Megatron-style). A group of size *n* whose ranks are *s* apart lies inside
one node when *n·s ≤ G*. It lies entirely on the scale-out network when
*s ≥ G*, with one GPU per node, all on the same rail. Otherwise it is
hierarchical.

**Per-step traffic** (one optimizer step, *m* microbatches, activation
A = micro_batch · seq · hidden · dtype bytes):

| Parallelism | Collective | Size per call | Calls per step | Typical network |
|---|---|---|---|---|
| DP (gradient sync) | all-reduce, or reduce-scatter + all-gather for FSDP/ZeRO | params/(TP·PP) · dtype | 1 | scale-out (hierarchical when TP < G) |
| TP (Megatron) | all-reduce | A | 4 per layer per microbatch: "two all-reduces in the forward path and two in the backward path" (S17) | scale-up (keep TP ≤ G) |
| PP | send/recv | A (upper bound; implementations can shard it) | 2 per microbatch (activation forward, gradient backward) | scale-out |
| EP (MoE) | all-to-all | micro_batch · seq · top_k · hidden · dtype | 4 per MoE layer per microbatch (dispatch + combine, forward and backward) | both when EP spans nodes |
| Inference P/D | KV-cache transfer | KV B/token · prompt tokens | per request | scale-out |

The per-step compute estimate is `6 · active params · tokens / (GPUs · peak · MFU)`,
with peak = 989.5 dense BF16 TFLOPS (S5) and MFU = 0.40 (A5). Communication is
assumed not to overlap compute (A6), so step times are upper bounds.

### 2.2 Training examples

Inputs: the Llama 3 shapes (S13); Mixtral with 8 experts, top-2 (S18), and the
Mistral-7B shape (A9); 400G NICs (S1); 450 GB/s NVLink (S4); 80 % efficiency
(A1, A2); α = 5 µs / 1 µs (A3, A4). Command:
`python -m fabric.design.collectives --section training`.

<!-- design-table:training -->
**8B on 256 GPUs** (TP 1 · PP 1 · DP 256 · EP 1; seq 8,192, 1 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---|---:|---|---:|---:|---:|---:|
| DP | all-reduce (gradients) | 256 | both (NVLink + scale-out) | 1 | 28.000 | 3.875 | 174.98 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 993.47 |
| **step** | compute + exposed comm |  |  |  |  |  | 1,168.45 |

**70B on 256 GPUs** (TP 8 · PP 4 · DP 8 · EP 1; seq 8,192, 16 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---|---:|---|---:|---:|---:|---:|
| TP | all-reduce (activations) | 8 | scale-up (NVLink) | 1,280 | 300.648 | 0 | 853.05 |
| PP | send/recv (activations) | 4 | scale-out (backend) | 32 | 0 | 4.295 | 107.53 |
| DP | all-reduce (gradients) | 8 | scale-out (backend) | 1 | 0 | 7.656 | 191.48 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 4,346.44 |
| **step** | compute + exposed comm |  |  |  |  |  | 5,498.50 |

**405B on 2,048 GPUs** (TP 8 · PP 16 · DP 16 · EP 1; seq 8,192, 32 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---|---:|---|---:|---:|---:|---:|
| TP | all-reduce (activations) | 8 | scale-up (NVLink) | 896 | 420.907 | 0 | 1,181.73 |
| PP | send/recv (activations) | 16 | scale-out (backend) | 64 | 0 | 17.180 | 429.82 |
| DP | all-reduce (gradients) | 16 | scale-out (backend) | 1 | 0 | 11.865 | 296.78 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 12,573.62 |
| **step** | compute + exposed comm |  |  |  |  |  | 14,481.95 |

**Mixtral 8x7B on 256 GPUs** (TP 2 · PP 1 · DP 128 · EP 8; seq 4,096, 1 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---|---:|---|---:|---:|---:|---:|
| TP | all-reduce (activations) | 2 | scale-up (NVLink) | 128 | 4.295 | 0 | 12.19 |
| EP | all-to-all (tokens) | 8 | both (NVLink + scale-out) | 128 | 3.221 | 4.295 | 120.80 |
| DP | all-reduce (gradients) | 128 | both (NVLink + scale-out) | 1 | 70.500 | 22.766 | 765.29 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 403.60 |
| **step** | compute + exposed comm |  |  |  |  |  | 1,301.88 |
<!-- /design-table -->

How to read the tables:

- **8B, pure DP.** The 16 GB gradient (8 B params × 2 B) is all-reduced once
  per step. Hierarchical reduction cuts the bytes each GPU sends on its NIC to
  2·31/32 · 16/8 = 3.875 GB, against 2·255/256 · 16 = 31.9 GB for a flat ring over 256 GPUs (CALCULATED).
  Each GPU's share crosses the fabric on its own rail, so the gradient
  all-reduce is rail-local traffic.
- **70B, TP 8 · PP 4 · DP 8.** TP produces the most bytes (≈ 300 GB per GPU
  per step), but all of it stays on NVLink. The scale-out fabric carries only
  PP sends (≈ 4.3 GB) and the DP all-reduce (≈ 7.7 GB). Because DP ranks are
  8 apart (stride = TP = G), each DP group consists of same-index GPUs on 8
  different nodes, so it is one rail. This is the reason for rail-optimized
  fabrics (§3).
- **Mixtral, EP 8 after TP 2.** The EP group spans 2 nodes (4 GPUs each), so
  about half of the all-to-all goes over the fabric. All-to-all is the one
  pattern here that is any-to-any and cross-rail. The DP row reduces all 47 B
  parameters over DP 128. That is an upper bound: in practice expert weights
  are reduced only over DP/EP ranks.

### 2.3 One slow link

In a ring every rank waits for its predecessor, so the whole ring runs at the
rate of its slowest link. If one link runs at a fraction *f* of its rate, the
bandwidth term becomes `2(N−1)/N · S / (f·B)`. In a hierarchical all-reduce
the NVLink phases are unaffected and only the inter-node ring slows down. The
other rails then wait for the slow rail at the final all-gather. Command:
`python -m fabric.design.collectives --section slow-link`.

<!-- design-table:slow-link -->
**One link at 50% rate in the inter-node ring — 8B on 256 GPUs** — CALCULATED

| Quantity | All links healthy (ms) | One slow link (ms) | Change |
|---|---:|---:|---:|
| DP gradient all-reduce | 174.98 | 271.85 | +55.4% |
| Step (compute + exposed comm) | 1,168.45 | 1,265.32 | +8.3% |
<!-- /design-table -->

So one degraded optic or one NIC that has fallen back to a lower speed, out of
256 GPU links, slows every GPU in the job. How much depends on how much
communication is exposed: under the no-overlap assumption (A6) it is +8 % per
step here, and the collective itself is +55 %. A pure ring with no NVLink
phase (unit test: N = 8, f = 0.5) doubles. This is why per-link telemetry and
fast removal of degraded links matter more in an AI fabric than average link
utilisation does (§6, F4).

### 2.4 Inference: prefill/decode disaggregation

When prefill and decode run on different GPUs, each request's KV cache
crosses the scale-out network once:

```
KV bytes/token = 2 (K and V) · layers · kv_heads · head_dim · dtype bytes
bandwidth      = KV bytes/token · prompt tokens · requests/s
```

For Llama-3.2-3B (28 layers, 8 KV heads, head_dim 128, BF16; S14) this gives
2 · 28 · 8 · 128 · 2 = **114,688 B/token**. That is the same value as this
repository's T4 run ([benchmarks/results/t4/summary.md](../benchmarks/results/t4/summary.md)),
and it is a unit test. Command: `python -m fabric.design.collectives --section inference`.

<!-- design-table:inference -->
**Prefill → decode KV-cache transfer** — CALCULATED

| Model | KV B/token | Prompt tokens | KV MB/request | Requests/s | Scale-out Gb/s needed | 400G NICs @ 80% | One request on one NIC (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| llama3.2-3b | 114,688 | 2,048 | 234.9 | 10 | 18.8 | 1 | 5.87 |
| llama3-8b | 131,072 | 4,096 | 536.9 | 20 | 85.9 | 1 | 13.42 |
| llama3-70b | 327,680 | 4,096 | 1,342.2 | 20 | 214.7 | 1 | 33.55 |
| llama3-70b | 327,680 | 32,768 | 10,737.4 | 5 | 429.5 | 2 | 268.44 |
<!-- /design-table -->

In aggregate the bandwidth is modest: one 400G NIC covers the first three
cases. The constraint is latency, because the last column adds directly to
TTFT. A 32k-token 70B prompt needs about 270 ms on one NIC. Spreading it
across a node's 8 rails, or keeping prefill and decode within one NVLink
domain, avoids that.

## 3. Topology choice for the backend

### 3.1 Options

- **Rail-optimized leaf-spine** (S9). NIC *r* of every node connects to rail
  *r*'s leaf group. In S9's words, "Traffic per rail … is always one hop away
  from the other 31 nodes in a SU". The spine carries cross-rail traffic and
  traffic between scalable units.
- **Plain leaf-spine.** One leaf per rack, and all of a node's NICs go to that
  rack's leaf. Cabling is the simplest, and NIC links can be in-rack copper
  (≤ 3 m passive DAC, S19). Same-rail peers on other racks are 3 hops away.
- **Rail-only** (Wang et al., S11). Removes the spine. Each rail is its own
  network, and cross-rail traffic is first forwarded over NVLink to the GPU on
  the right rail. The paper claims 38–77 % lower network cost; that is the
  paper's own study.

**Why rails.** §2.2 shows that with TP inside the node, the DP groups and PP
neighbours are same-index GPUs on different nodes. They are rail-aligned. The
hierarchical all-reduce also keeps each GPU's inter-node share on its own
rail. A rail-optimized fabric puts most of that traffic one switch hop apart.
That saves latency, but it also takes the spine (and spine ECMP) out of the
path for most bytes.

**ECMP and entropy.** ECMP chooses one path per flow. F1's E1
([experiments/E1-ecmp-hash.md](experiments/E1-ecmp-hash.md); EMULATED Linux
kernel hashing, not an ASIC) measured 4 flows splitting 75/25 in two of three
repeats under L4 hashing, and every L3-hash run used a single uplink. AI
collectives have exactly this shape: few flows, each at line rate (S12). Meta
reports that "ECMP rendered poor performance for the training workload due to
the low flow entropy" (S12). Llama 3 training used 16 flows per GPU pair plus
enhanced ECMP over extra RoCE header fields (S13). Keeping traffic on the rail
leaf reduces how much of it is exposed to this problem. The rest is handled by
more flows per connection or by adaptive routing and packet spraying (§5/§6).

### 3.2 Counts at 256 and 2,048 GPUs

The switch is 51.2 Tb/s run as **128 × 400G** (SN5600 64×800G split 2×400G,
S6; the same split is available on Tomahawk 5, S7). 400G matches the
ConnectX-7 NIC (S1), so every backend link runs at one speed and the radix
doubles, which raises the 2-tier ceiling 4×. The backend is 1:1
(non-blocking; S10 calls it a "full fat-tree"), and there are 4 nodes per rack
(A7). Command: `python -m fabric.design.sizing`.

<!-- design-table:backend -->
**Backend, 256 GPUs (32 nodes × 8 × 400G NICs), 51.2T switch as 128 x 400G (SN5600, S6; Tomahawk 5, S7), oversubscription 1:1** — CALCULATED

| Topology | Tiers | Leaves | Spines | Super-spines | NIC–leaf links | Switch–switch links | Copper-capable links | Optical transceivers (both ends) | Same-rail GPU pairs at 1 switch hop | Max switch hops | Bisection (Tb/s) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| rail-optimized leaf-spine | 2 | 8 | 2 | 0 | 256 | 256 | 0 | 1,024 | 100% | 3 | 51.2 |  |
| plain leaf-spine (leaf per rack) | 2 | 8 | 2 | 0 | 256 | 256 | 256 | 512 | 10% | 3 | 51.2 | NIC links in-rack, copper-capable (≤ 3 m, S19) |
| rail-only (no spine) | 1 | 8 | 0 | 0 | 256 | 0 | 0 | 512 | 100% | 1 (cross-rail: NVLink + 1) | n/a | no network path between rails; per-rail bisection 6.4 Tb/s |

**Backend, 2,048 GPUs (256 nodes × 8 × 400G NICs), 51.2T switch as 128 x 400G (SN5600, S6; Tomahawk 5, S7), oversubscription 1:1** — CALCULATED

| Topology | Tiers | Leaves | Spines | Super-spines | NIC–leaf links | Switch–switch links | Copper-capable links | Optical transceivers (both ends) | Same-rail GPU pairs at 1 switch hop | Max switch hops | Bisection (Tb/s) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| rail-optimized leaf-spine | 2 | 32 | 16 | 0 | 2,048 | 2,048 | 0 | 8,192 | 25% | 3 | 409.6 |  |
| plain leaf-spine (leaf per rack) | 2 | 64 | 16 | 0 | 2,048 | 2,048 | 2,048 | 4,096 | 1% | 3 | 409.6 | NIC links in-rack, copper-capable (≤ 3 m, S19) |
| rail-only (no spine) | 2 | 32 | 16 | 0 | 2,048 | 2,048 | 0 | 8,192 | 25% | 3 (cross-rail: NVLink + 3) | n/a | no network path between rails; per-rail bisection 51.2 Tb/s |
<!-- /design-table -->

How the counts are derived (CALCULATED; the algebra is in `sizing.py` and the
unit tests):

- A leaf with radix *k* at 1:1 has *k/2* ports down and *k/2* up.
  Leaves = Σ over rails (or racks) of ⌈endpoints / (k/2)⌉. Spines =
  ⌈leaves · uplinks / k⌉, rounded up so that every leaf has the same number of
  links to every spine.
- **Optical transceivers** = 2 × (optical links), one at each end. NIC-to-leaf
  links count as optical when a leaf serves more nodes than one rack holds
  (A7), and switch-to-switch links are always optical (A8; spines sit in
  another row, > 3 m). With 800G twin-port OSFP modules on the switch side,
  the switch-end module count is lower. That depends on the breakout chosen
  (S6), and the model does not count modules.
- **Cross-check against a published design.** At radix 64 (QM9700, S8) the
  same code reproduces S9's DGX SuperPOD compute fabric exactly: 1 SU
  (31 nodes) gives 8 leaves, 4 spines and 256 spine-leaf links; 4 SU
  (127 nodes) gives 32 leaves, 16 spines and 1,024 links. These are unit tests.

What the counts show:

- At 256 GPUs, rail-optimized and plain leaf-spine use the **same switches**
  (8 leaves, 2 spines). They differ in wiring. Rail-optimized puts 100 % of
  same-rail pairs one hop apart but needs optics on every NIC link (1,024
  transceivers vs 512). Plain puts only 10 % of same-rail pairs one hop apart
  (the other nodes in the same rack).
- Rail-only removes the 2 spines and their 256 links. That saves half the
  transceivers. It works only while cross-rail traffic (MoE all-to-all, the
  any-to-any exchange in §2.2) can go through NVLink.
- At 2,048 GPUs, rail-only needs a leaf-spine *inside* each rail (256 nodes >
  128 ports), and it ends up with the **same** 32 leaves, 16 spines and
  2,048 links as rail-optimized. Its saving disappears once one rail no
  longer fits on one switch, which here means above 128 nodes (1,024 GPUs).

### 3.3 Where two tiers stop

Each spine port reaches a different leaf, so a 2-tier Clos has at most *k*
leaves × *k/2* hosts = **k²/2** endpoints. A 3-tier fat tree has *k* pods ×
*k²/4* = **k³/4**. Hops between GPUs go from 3 to 5. Command:
`python -m fabric.design.sizing`.

<!-- design-table:ceiling -->
**Where two tiers stop (non-blocking; one NIC per GPU)** — CALCULATED

| Switch configuration | Radix k | Port speed | 2-tier max NICs = k²/2 | 2-tier max GPUs (8 NICs/node) | 3-tier max NICs = k³/4 |
|---|---:|---|---:|---:|---:|
| 51.2T as 128 x 400G (S6, S7) | 128 | 400G | 8,192 | 8,192 | 524,288 |
| 51.2T as 64 x 800G (S6, S7) | 64 | 800G | 2,048 | 2,048 | 65,536 |
| Quantum-2 QM9700 64 x 400G (S8) | 64 | 400G | 2,048 | 2,048 | 65,536 |
<!-- /design-table -->

The ceiling depends on radix at the NIC speed, not on switch capacity. The
same 51.2 Tb/s chip gives 8,192 GPUs in 2 tiers with 400G NICs, but only
2,048 once NICs move to 800G. 2,048 GPUs on 64-port switches sits exactly at
the 2-tier limit, with no room to grow. Above the ceiling, production designs
add a third tier. Llama 3's 24k-GPU cluster used a 3-layer Clos with
full-bisection 3,072-GPU pods and 1:7 oversubscription between pods (S13);
Meta's AI Zone adds an ATSW layer above the RTSW/CTSW Clos (S12).

> **Sensitivities: assumptions that would change a conclusion if wrong**
>
> | Input | Default | If it changes… |
> |---|---|---|
> | NICs per node (S1) | 8, one per GPU | With 4 NICs/node (2 GPUs per NIC), rails halve, NIC links halve, and the hierarchical all-reduce puts 2× the bytes on each NIC (same node total over half the NICs). The rail argument still holds; rerun `sizing.py` with `nics_per_node: 4` for counts. |
> | NIC speed vs. switch radix (S1, S6) | 400G → k = 128 | At 800G NICs k = 64: the 2-tier ceiling falls from 8,192 to 2,048 GPUs, and 2,048 GPUs no longer has headroom. This is the conclusion most sensitive to hardware generation. |
> | Network efficiency (A1) | 0.80 | Every scale-out time scales by 1/efficiency. Results are linear, so 0.9 gives about 11 % faster times. No topology conclusion changes. |
> | MFU and overlap (A5, A6) | 0.40, none | The one-slow-link job slowdown (+8.3 %) is an upper bound. With full overlap of DP traffic it could approach 0 while compute hides it, and with lower MFU it shrinks further. The +55 % collective slowdown does not depend on these. |
> | Rank layout (TP innermost) | Megatron-style | If DP were innermost, TP would cross nodes and land on the fabric. The "most traffic is rail-local" argument depends on keeping TP ≤ GPUs per node. |
> | Nodes per rack (A7) | 4 | It decides which NIC links can be copper (transceiver count) and the plain topology's 1-hop fraction. Leaf and spine counts do not change. |
> | Cross-rail share of traffic | small for dense TP×DP×PP | MoE all-to-all is cross-rail. A heavily MoE workload favours a spine (rail-optimized) over rail-only. |
> | Per-step latency α (A3, A4) | 5 µs / 1 µs | It matters only for small messages. All §2 tables are bandwidth-dominated. |

## 4. Lab → production mapping

The F1 lab ([README.md](README.md), [ADR 0004](../docs/adr/0004-fabric-intent-render.md))
is a miniature rail-optimized leaf-spine: 2 spines, 4 leaves, and 4 dual-NIC
hosts. Rail A is leaves 1–2 and rail B is leaves 3–4. It uses eBGP over IPv6
link-local addresses with RFC 8950 next hops, two-way ECMP, and BFD at
100 ms × 3. All results are EMULATED.

| Production concept | In the F1 lab | Production equivalent | Transfers? |
|---|---|---|---|
| Rails (one NIC per GPU index) | 2 rails, one NIC per rail per host | 8 rails (S1); a leaf group per rail (S9) | **Yes** for the design logic: per-rail addressing, source-policy routing per NIC, and the validator check of "exactly one NIC per rail" |
| Leaf-spine Clos, eBGP, unique leaf ASN | 2 × 4, eBGP unnumbered, spine AS 65000 (RFC 7938) | Same pattern at 8–32 leaves × 2–16 spines (§3.2) | **Yes** for the control-plane design; the intent/render model scales by data, not by code |
| ECMP | 2-way, Linux kernel hash (E1) | Wide ECMP in the switch ASIC hash, with adaptive routing or spraying options (vendor-specific) | **Concept only.** E1 shows the low-entropy problem, but it measured Linux hashing, not an ASIC |
| Failure detection | BFD: silent-loss recovery about 1.0–1.1 s vs 7.9–9.7 s on the hold timer (E2) | BFD or ASIC link-fault signalling, with timers validated on the target platform | **Concept only.** The timings are veth/kernel timings |
| Line rate | veth, no rate | 400G per NIC, 51.2T per switch | **No** |
| Buffers, PFC, ECN/DCQCN | none | A lossless or congestion-controlled RoCE v2 class (§5) | **No.** F3 starts Soft-RoCE/QoS |
| ASIC hashing, adaptive routing, packet spraying | none | Vendor features (Spectrum-X, Tomahawk 5 / Jericho, InfiniBand AR) | **No** |
| NVLink / scale-up | none (hosts are containers) | NVSwitch at 450 GB/s per GPU per direction (S4) | **No.** Modelled only in §2 (CALCULATED) |
| Front-end, storage, OOB | containerlab management network only | Three separate networks (§1) | **Partly:** only the idea of a separate management plane |
| Scale (2-tier ceiling, transceivers, power) | 6 switches, 8 host links | §3 tables | **No.** Calculated only |

## 5. RoCE v2 and lossless transport

RoCE v2 carries RDMA over UDP/IP (destination port 4791); RC QPs provide
reliable delivery, but losslessness is a fabric QoS design rather than a
property of the transport. This repository's class mapping is
**INTENT-ONLY**: RoCE DSCP 26 → TC3 / PFC priority 3, CNP DSCP 48 → strict
TC6, and unmarked traffic → default TC0. The SONiC `config_db` render has not
been applied to a switch. Host `tc` confirms DSCP classification, but its
`prio` qdisc is strict priority, not the intent's 50/50 DWRR scheduler.
Sources and vendor-specific field mappings are in
[`qos/README.md`](qos/README.md).

The original container hosts can create `rdma_rxe` devices and expose
RoCE-v2 IPv4-mapped GIDs, but on the measured WSL2 Linux 6.18 kernel rxe
routes and UDP 4791 receive sockets are bound to `init_net`. Consequently,
verbs traffic from those container network namespaces fails. Two small QEMU
VM hosts solve the experimental endpoint problem by giving each rxe device
its own guest kernel and initial namespace: 768 MiB and 2 vCPUs per VM, KVM
on the measured host (TCG fallback). These are **SOFT-ROCE** endpoints over
the **EMULATED** veth fabric, not NICs. See [E3](experiments/E3-soft-roce.md)
for VM/image/package checksums, sources, commands, and raw results.

E3 observed 200/200 captured RoCE data packets as DSCP 26 / Not-ECT with
`--tclass 104`; the host tc counter moved into the RoCE band. The capture
decoded BTH opcode, destination QP, PSN, and AckReq. With L3 ECMP hashing,
all same-IP-pair QPs selected spine2 despite distinct per-QP UDP source
ports. This demonstrates packet formatting and Linux forwarding only.

Lossless buffer arithmetic is design guidance, not a test of PFC. The intent
sets ECN Kmin/Kmax to 150,000/1,500,000 B and PFC XOFF to 3,000,000 B, so
ECN is intended to mark before pause. At 400 Gbit/s, the conservative IEEE
response calculation gives 72.8 KB at 3 m and 76.4 KB at 10 m per port per
priority. On a 64 × 800G, 128 MB example, one H3C-response lossless class
reserves 5.8% at 100 m; two reserve 11.6%. Refer to
[`tools/headroom.py`](tools/headroom.py) and the cited assumptions in
[`qos/README.md`](qos/README.md). No PFC, switch buffers, or NIC pause
behavior exists in the EMULATED lab.

## 6. Congestion control and telemetry

ECN should signal congestion before PFC XOFF, giving endpoints time to
reduce load and limiting pause propagation. DCQCN is the intended RoCE
congestion-control mechanism, but it is **INTENT-ONLY** in this work: rxe
does not implement DCQCN, the lab does not implement PFC, and Linux qdisc CE
marks are not switch ECN behavior.

E4 scaled the intent's RED thresholds to a 500 Mbit/s Linux TBF bottleneck
(effective Kmin/Kmax 1,500/3,000 B; scaled XOFF 3,750 B). The prediction was
that ECN-on TCP would react to CE with ECE/CWR and that Not-ECT TCP would be
dropped; SOFT-ROCE would show CE but no CNP or rate reaction. Measurements:

| Test | Prediction | Measured |
|---|---|---|
| TCP ECN on | CE, ECE/CWR, useful throughput | 103/1200, 129/1200, 103/1200 sampled packets CE; ECE 146/193/124, CWR 24/33/21; RX 0.402/0.396/0.394 Gbit/s |
| TCP ECN off | Not-ECT drops; no ECN response; lower or less stable throughput | 1200/1200 packets Not-ECT per repeat; no ECE/CWR; RX 0.435/0.445/0.442 Gbit/s, higher than predicted |
| SOFT-ROCE | CE likely; no CNP/DCQCN response | 17/1200 sampled packets CE, zero BTH opcode `0x81` CNPs; reported 0.46 Gbit/s under the shaper |

No conclusion about real DCQCN response or PFC headroom follows from these
EMULATED/SOFT-ROCE data. The measurements and qdisc/capture evidence are in
[E4](experiments/E4-ecn.md).

E5 tested ring and all-to-all collective-shaped loads against the two-spine
Linux ECMP fabric. Prediction: L3 would pin streams within an IP pair; L4
would gain entropy as parallel flows/QPs increased, but remain lumpy.
Measured mean max/mean uplink-load imbalance for TCP was:

| Pattern | Hash | 1 flow/pair | 4 flows/pair | 16 flows/pair |
|---|---|---:|---:|---:|
| Ring | L3 | 1.998 | 1.998 | 1.997 |
| Ring | L4 | 1.998 | 1.217 | 1.248 |
| All-to-all | L3 | 1.530 | 1.541 | 1.515 |
| All-to-all | L4 | 1.668 | 1.296 | 1.119 |

L4 did not guarantee even distribution. E5's job times and the
counter-derived perfect-split estimates are explicitly distinguished; the
ideal estimate is not a second run or a measured speedup. Supplemental
SOFT-ROCE QP runs kept the fixed pair on spine2 with L3 and observed both
spines with L4 at 4/16 QPs. This is Linux hash behavior, not ASIC ECMP.
Meta's low-flow-entropy report and Llama 3's 16 flows per GPU pair (sources
S12/S13 in [`design/sources.md`](design/sources.md)) motivate the experiment;
they do not make the emulation a production model. Full results are in
[E5](experiments/E5-collective-entropy.md).

The dashboard [fabric.json](../observability/dashboards/fabric.json) uses a
host-side Python exporter for Linux interface/qdisc counters and FRR BGP/BFD
state. A standalone digest-pinned Prometheus is scraped locally; there is no
k3s scrape configuration and no successful gNMI stream. SR Linux 24.10.1
did not deploy successfully with containerlab 0.78.2/Podman, so the dashboard
data are **EMULATED** Linux/FRR telemetry, not gNMI or switch ASIC telemetry.
Exporter pins, failure evidence, and E5 query-range output are documented in
[`telemetry/README.md`](telemetry/README.md).

## 7. Tenancy and failure domains

TBD in F5.
