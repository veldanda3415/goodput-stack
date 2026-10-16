# E5 — Collective-shaped traffic and ECMP entropy

**Status:** unshaped matrix complete (job-time interpretation corrected
below); shaped-uplink rerun in [§ Shaped uplinks rerun](#shaped-uplinks-rerun).
TCP uses the four existing
rail-A hosts. The supplemental RDMA comparison uses the two VM endpoints
because the other four host namespaces cannot send rdma_rxe packets on this
WSL2 kernel (see [E3 §0](E3-soft-roce.md#0-feasibility-gate)).

## Predictions (written before the run)

| Transport / pattern | Hash | Flows/QPs per pair | Prediction |
|---|---|---:|---|
| TCP ring | L3 | 1, 4, 16 | Each fixed IP pair stays on one uplink; multiple flows do not increase entropy. |
| TCP ring | L4 | 1 | One flow selects one uplink; no split expected. |
| TCP ring | L4 | 4 | Some improvement, but a lumpy split is likely; E1 observed 50/50 to about 75/25. |
| TCP ring | L4 | 16 | Closer to an even split on average, not guaranteed. |
| TCP all-to-all | L3 | 1, 4, 16 | Distinct IP pairs can hash differently, while streams within any one pair remain pinned together. |
| TCP all-to-all | L4 | 1, 4, 16 | More flow entropy should help sharing as streams per pair grow, but hash collisions remain possible. |
| SOFT-ROCE VM pair | L3 | 1, 4, 16 QPs | The fixed IP pair should select one spine regardless of QP source ports. |
| SOFT-ROCE VM pair | L4 | 1, 4, 16 QPs | UDP source-port entropy may distribute QPs; an even split is not guaranteed. |

The low-entropy motivation is Meta Engineering's 2024 RoCE deployment report:
ECMP performance suffered from low flow entropy. Llama 3's production report
describes 16 flows per GPU pair and enhanced ECMP as a mitigation. These are
the project's source entries S12 and S13 in
[`design/sources.md`](../design/sources.md), not results from this emulation.

## Method

Run `make fabric-e5`. It refuses to overlap gateway probes, configures each
leaf's Linux `net.ipv4.fib_multipath_hash_policy` to L3 (`0`) then L4 (`1`),
and restores L3 (`0`) in `finally`. The four-host ring is
host1→host3→host2→host4→host1; all-to-all creates all 12 ordered distinct
pairs. Each pair uses one iperf3 client with 1, 4 or 16 parallel streams;
clients run for 5 seconds (`-t 5`), except 16-flow all-to-all cells run for
4 seconds to keep cell wall time below the 10-second cap. TCP targets
262,144 bytes per stream. Per-stream interval byte counts are accumulated and linearly
interpolated within the interval where a stream reaches that target. The
slowest stream's target completion offset from the first client launch is the
job time.

Every cell snapshots `ip -j -s link show` on all four leaves and records TX
byte deltas for every fabric uplink. Per-leaf imbalance is
`max(uplink bytes) / mean(uplink bytes)`, including idle ECMP members. The
"imbalance-implied bound" is a model: the observed job time divided by the
worst active-leaf max/mean ratio. (F4 called it the "ideal" job time.) It
restates the imbalance and is not a second measured execution or a claim about
ASIC capacity.

The supplementary SOFT-ROCE run sweeps parallel QPs between vmhost1 and
vmhost2, with 256 × 65,536-byte write iterations per QP. Perftest reports
aggregate bandwidth; the displayed mean per-QP bandwidth is aggregate/QP
count, not a directly sampled individual-QP rate. Bounded captures on both
spines decode UDP source ports and verify their observed path.

## Preflight adjustment

The initial `iperf3 -n` approach mistakenly treated its byte limit as a
per-parallel-stream target. The first ring/4-flow run exposed that error:
`iperf3 -c 10.210.0.10 -B 10.210.0.2 -p 5480 -P 4 -n 4194304 --json`
reported 1,441,792 B for stream 1, below the mistaken 4,194,304 B target.
Repeating with `-n 1048576` reported 393,216 B for stream 1, below the
mistaken 1,048,576 B target. The isolated same-leaf
host1→host2 command
`iperf3 -c 10.210.0.6 -B 10.210.0.2 -p 5901 -P 1 -n 4194304 --json`
received all 4,194,304 B in 1.001392 s at 33,507,789 bit/s. The three valid
4 MiB ring cells are retained in [`e5-4mb-partial.json`](e5-4mb-partial.json);
the fixed-byte pilot runs are retained in [`e5-1mb-partial.json`](e5-1mb-partial.json).
The final matrix instead runs fixed-duration streams and computes each
stream's time-to-262,144-B from iperf3 interval reports. The corrected
ring/four-stream pilot reached the per-flow target in 0.877531 s (16 flows;
minimum final receive 1,334,181,888 B) with 7.088075 s total cell wall time;
the exact commands and raw JSON are in
[`e5-ring4-pilot.json`](e5-ring4-pilot.json). A one-flow
all-to-all diagnostic (`iperf3 -c 10.210.0.6 -B 10.210.0.2 -p 6600 -P 1
-n 1048576 --json`) completed with 2.620928 s job time and 4.037922 s wall
time. Commands and pilot values are retained in the final results JSON.

## Measured results

The matrix was run with `make fabric-e5`; the completed continuation command
was `./.venv/bin/python -m fabric.tools.collective_gen --resume`. An initial
L4/all-to-all/16/repeat-2 cell took 10.024 s and triggered the 10-second cap.
The runner was made resumable; missing 16-flow all-to-all cells used
`iperf3 ... -P 16 -t 4 --json`. The final matrix contains 36 TCP and 18
SOFT-ROCE cells, no recorded cell above 10 seconds (max TCP cell wall time
9.597 s; max SOFT-ROCE time 4.918 s), no final failures, and
`restored_hash_policy: 0`. This is an **EMULATED** Linux/veth result.

Mean job time and imbalance are the arithmetic means of three repeats.
The last two columns are a **MODEL**, not evidence: the
"imbalance-implied bound" is measured job time ÷ max/mean imbalance, and
"imbalance − 1" restates the measured imbalance as a percentage. Neither is
an independent measurement of what better spreading would buy; the
[correction below](#correction-job-time-did-not-measure-the-fabric) shows
that unshaped job time did not depend on uplink load at all.

| Transport / pattern | Hash | Flows/QPs | Prediction | Measured max/mean | Measured job (s) / imbalance-implied bound (model, s) | Imbalance − 1 (model) |
|---|---|---:|---|---:|---:|---:|
| TCP ring | L3 | 1 | One path per fixed IP pair | 1.998 | 0.892 / 0.446 | 99.8% |
| TCP ring | L3 | 4 | Still one path per fixed IP pair | 1.998 | 0.906 / 0.453 | 99.8% |
| TCP ring | L3 | 16 | Still one path per fixed IP pair | 1.997 | 0.902 / 0.452 | 99.7% |
| TCP ring | L4 | 1 | One path | 1.998 | 0.912 / 0.456 | 99.8% |
| TCP ring | L4 | 4 | Some sharing, likely lumpy | 1.217 | 0.902 / 0.746 | 21.7% |
| TCP ring | L4 | 16 | Closer to even, not guaranteed | 1.248 | 0.899 / 0.721 | 24.8% |
| TCP all-to-all | L3 | 1 | Distinct IP pairs share unevenly | 1.530 | 1.713 / 1.119 | 53.0% |
| TCP all-to-all | L3 | 4 | Per-pair streams remain together | 1.541 | 1.780 / 1.155 | 54.1% |
| TCP all-to-all | L3 | 16 | Per-pair streams remain together | 1.515 | 2.044 / 1.353 | 51.5% |
| TCP all-to-all | L4 | 1 | Multiple IP pairs; still lumpy | 1.668 | 1.766 / 1.079 | 66.8% |
| TCP all-to-all | L4 | 4 | Better aggregate sharing expected | 1.296 | 1.810 / 1.398 | 29.6% |
| TCP all-to-all | L4 | 16 | Better sharing; collisions remain | 1.119 | 1.923 / 1.727 | 11.9% |

L3 ring imbalance remained near 2.0 regardless of stream count, as predicted.
L4 improved sharing for ring 4/16-flow and all-to-all 4/16-flow cases; the
best mean was 1.119 for 16-flow all-to-all. L4 did not guarantee a balanced
hash: the ring's 16-flow imbalance (1.248) was slightly worse than 4-flow
(1.217), and all-to-all/1 had one repeat at 1.998. These are Linux
hash-policy measurements, not switch ASIC behavior. The imbalance-implied
bound assumes equal-capacity uplinks and job time proportional to the worst
active-leaf ratio; the correction below shows that assumption failed here, so
it must not be read as a measured or achievable gain.

### Correction: job time did not measure the fabric

Added after F4 review; recomputed from the retained
[`e5-results.json`](e5-results.json) only (no rerun). **EMULATED.**

Better spreading did not shorten measured job time. Ring job time was about
0.9 s in every cell, from imbalance 1.998 down to 1.217. All-to-all got
*slower* as flows/pair rose (L4: 1.766 → 1.810 → 1.923 s) while its imbalance
fell (1.668 → 1.296 → 1.119). The uplinks were therefore not the bottleneck.

Splitting each cell's job time shows why. The runner launches each pair's
iperf3 client with a separate, serial `containerlab exec`. The job-time origin
is the first launch, so job time includes every later client's launch
offset. Per cell (means of three repeats):

| Pattern | Hash | Flows/pair | Max/mean | Measured job (s) | Last client launch offset (s) | Slowest flow's own time to 256 KiB (ms) | Aggregate received (Gbit/s) |
|---|---|---:|---:|---:|---:|---:|---:|
| ring | L3 | 1 | 1.998 | 0.892 | 0.892 | 0.3 | 32.3 |
| ring | L3 | 4 | 1.998 | 0.906 | 0.904 | 1.2 | 38.8 |
| ring | L3 | 16 | 1.997 | 0.902 | 0.896 | 6.4 | 38.4 |
| ring | L4 | 1 | 1.998 | 0.912 | 0.912 | 0.3 | 29.4 |
| ring | L4 | 4 | 1.217 | 0.902 | 0.901 | 1.1 | 40.5 |
| ring | L4 | 16 | 1.248 | 0.899 | 0.894 | 5.2 | 39.8 |
| all-to-all | L3 | 1 | 1.530 | 1.713 | 1.713 | 0.9 | 42.9 |
| all-to-all | L3 | 4 | 1.541 | 1.780 | 1.777 | 4.1 | 44.1 |
| all-to-all | L3 | 16 | 1.515 | 2.044 | 2.021 | 37.0 | 46.7 |
| all-to-all | L4 | 1 | 1.668 | 1.766 | 1.766 | 0.9 | 44.0 |
| all-to-all | L4 | 4 | 1.296 | 1.810 | 1.807 | 4.3 | 45.8 |
| all-to-all | L4 | 16 | 1.119 | 1.923 | 1.909 | 28.1 | 47.6 |

Launch offset is more than 98% of every job time. Ring (4 clients) lands near
0.9 s and all-to-all (12 clients) near 1.7–2.0 s. The network part (the slowest
flow's time to 256 KiB after its own start) is 0.3–37 ms. It grows with the
number of concurrent flows (192 TCP flows at all-to-all/16) and with the
aggregate the four host containers drive, 29–48 Gbit/s on one WSL2 VM
(16 vCPUs). That points at host/veth/CPU and orchestration costs, not at the
uplinks. Per-host CPU was not recorded in these TCP cells. It is measured in
the [shaped rerun](#shaped-uplinks-rerun), which also replaces the serial
launch with a synchronized start.

What remains valid from the unshaped matrix: the uplink byte splits
(max/mean columns) are counter measurements of Linux hash behavior. What is
not valid: any statement that the measured imbalance cost job time, or that
the model column is an achievable speedup.

Supplemental two-VM **SOFT-ROCE** `ib_write_bw` results (mean aggregate rate
from three repeats):

| Hash | QPs | Mean aggregate Gbit/s | Captured distinct UDP source ports per repeat | Captured paths |
|---|---:|---:|---|---|
| L3 | 1 | 0.607 | 1 / 1 / 1 | spine2 only |
| L3 | 4 | 0.750 | 2 / 2 / 2 | spine2 only |
| L3 | 16 | 0.863 | 2 / 2 / 2 | spine2 only |
| L4 | 1 | 0.513 | 1 / 1 / 1 | spine1 once; spine2 twice |
| L4 | 4 | 0.743 | 3 / 3 / 4 | both spines |
| L4 | 16 | 0.833 | 4 / 4 / 4 | both spines |

Each spine tap capture was limited to 128 packets; the observed ports can be
a subset of QPs. The individual `capture_by_tap` port lists and the
source-leaf uplink TX deltas are recorded in the JSON. L3 kept the fixed IP
pair on spine2 for all QP counts. L4 showed both spines at 4/16 QPs but did
not make each QP a distinct hash flow in the bounded sample. Bandwidth is the
perftest aggregate; equal-share per-QP rates are derived, not per-QP
measurements. **SOFT-ROCE** uses CPU software over the EMULATED veth fabric
and is not NIC performance.

The production motivation is Meta's low-flow-entropy report (S12) and Llama
3's 16 flows per GPU pair / enhanced ECMP description (S13), both listed in
[`design/sources.md`](../design/sources.md). Those references motivate the
sweep but do not validate this emulation as an ASIC model.

Raw per-flow iperf3 JSON, commands, uplink snapshots/deltas, perftest output,
and tap captures are preserved in [`e5-results.json`](e5-results.json) and
`e5/`.

## Shaped uplinks rerun

**Label: EMULATED (veth + Linux forwarding), SHAPED to 500 Mbit/s per
leaf↔spine direction.** These numbers are Linux TBF + TCP behavior on veth,
not switch or NIC performance. The unshaped results above are kept unchanged.

### Measure first (unshaped capacity)

Command: `.venv/bin/python -m fabric.experiments.e5_shaped baseline`
(raw: [`e5-shaped-baseline.json`](e5-shaped-baseline.json)).

| Measurement | Command | Result |
|---|---|---|
| Single flow, host1 → host3 (cross-spine), 3 × 5 s | `iperf3 -c 10.210.0.10 -B 10.210.0.2 -P 1 -t 5 --json` | 8.22 / 8.25 / 8.20 Gbit/s; sender CPU 99.3% (98.8–99.2% system), receiver 39–41% |
| Per-host aggregate, ring, 16 flows/pair, 3 × 5 s, synchronized start | `e5_shaped baseline` (`-P 16 -t 5`) | 9.75–10.72 Gbit/s sent per host |
| Per-host aggregate, all-to-all, 16 flows/pair, 3 × 5 s | same | 9.49–10.62 Gbit/s sent per host |
| Host CPU during those cells | cgroup v2 `cpu.stat usage_usec` per container; `/proc/stat` system-wide | 0.99–1.19 cores per host container; 56–61% of the WSL2 VM's 16 vCPUs busy |

The container cgroup figure undercounts: veth softirq work is charged to
whichever context runs it, so the system-wide 56–61% is the better total.
Either way, about 10 Gbit/s per host with a single flow pinned at 99% of one
core means hosts, veths, and CPU set the unshaped limit, consistent with the
correction above.

### Shaping rate choice

`lab_shaping.uplink_rate_mbit: 500` in [`../intent/fabric.yaml`](../intent/fabric.yaml),
rendered to `tc qdisc replace dev <port> root tbf rate 500mbit burst 125000
limit 625000` on both ends of all eight leaf↔spine links (16 directional
ports; `fabric/build/shaping/<router>-shape-{on,off}.sh`;
`make fabric-shape-on/off`). Why 500 Mbit/s:

- It is 1/20 of the measured per-host aggregate (≈10 Gbit/s), below the
  required ≤ ¼ (2.5 Gbit/s). It is also 1/16 of a single flow.
- Worst case, a leaf sends two uplinks' worth (2 × 500 Mbit/s) from two
  hosts, about 0.5 Gbit/s per host, or 5% of measured host capacity. Host CPU
  therefore cannot be what limits job time.
- It equals E4's RED bottleneck rate, so E4/E5/E6 share one emulated speed.
- `burst` 125,000 B (2 ms at rate, above rate/HZ per
  [tc-tbf(8)](https://man7.org/linux/man-pages/man8/tc-tbf.8.html)
  *PARAMETERS*) and `limit` 625,000 B (10 ms of queue).

Sanity check after `make fabric-shape-on`: one flow host1 → host3 received
0.497 Gbit/s (11 retransmits) for 3 s; `fabric.tools.shaping status` showed
16/16 fabric ports with `tbf` at 62,500,000 B/s.

### Method

`python -m fabric.experiments.e5_shaped run` (shaping must be ON).

- **Synchronized start.** Each client runs
  `sh /tmp/e5sync.sh <T0> timeout 30 iperf3 -c <dst> -B <src> -P <N> -n <bytes> --json`,
  which sleeps until the absolute epoch T0, set 1.5 s after launch. All
  containers share the WSL2 kernel clock. Job time = last client exit − T0,
  and the recorded start skew is max − min of the clients' actual start stamps.
- **Fixed bytes per pair** (`-n`; the total across the `-P` streams), sized so
  that an even split takes 3 s at 500 Mbit/s. Ring: 187,500,000 B/pair (each
  leaf sources two cross-leaf pairs → one per uplink at full rate).
  All-to-all: 93,750,000 B/pair (four cross-leaf pairs per leaf → two per
  uplink). Same-leaf all-to-all pairs do not cross the fabric.
- **Routing modes.** L3 (`fib_multipath_hash_policy=0`), L4 (`=1`), and
  **pinned**: the measured even-split baseline. Policy rules rendered from
  intent (`fabric/build/shaping/<leaf>-pin-<pattern>.sh`) send each
  cross-leaf (src IP, dst IP) pair to an alternating uplink via
  `169.254.0.1 dev ethN onlink`, the permanent neighbor FRR installs for
  unnumbered BGP. That gives 1 ring pair or 2 all-to-all pairs per uplink.
  The pinned run is a second measured execution, not a model.
- **Measured per cell:** TX bytes on all 16 shaped ports (leaf and spine
  side), TBF drops, per-container CPU, iperf3 retransmits. "Max-link bound"
  = busiest directional link's bytes × 8 / 500 Mbit/s: how long that link
  alone needed.

### Predictions (written before the run)

| Pattern | Routing | Flows/pair | Predicted job time | Reasoning |
|---|---|---:|---|---|
| ring | pinned | 1, 16 | ≈ 3.1–3.3 s | one pair per uplink; 3 s of payload + headers + TCP ramp |
| ring | L3 | 1, 16 | ≈ 6–6.5 s (≈ 2× pinned), imbalance ≈ 2.0 | unshaped E5 measured 1.998: both pairs of each leaf hash to one uplink; flows/pair cannot help |
| ring | L4 | 1 | 3 or 6 s per repeat, mostly 6 | two flows per leaf: 50% collision per leaf, worst of 2 leaves → P(no collision anywhere) = 25% |
| ring | L4 | 16 | ≈ 3.1–3.6 s | 32 flows per leaf; with a per-pair byte target, a pair whose flows sit on both uplinks keeps both links busy (work-conserving), so job time approaches pinned even if flow counts are uneven |
| all-to-all | pinned | 1, 16 | ≈ 3.1–3.3 s | two pairs per uplink |
| all-to-all | L3 | 1, 16 | ≈ 4.5 s if 3:1 (imbalance 1.5), 6 s if 4:0 | unshaped E5 measured 1.51–1.54 → expect 3:1 and ≈ 4.5 s |
| all-to-all | L4 | 1 | 3–6 s, most likely ≈ 4.5 s | four flows per leaf: P(2:2) 37.5%, P(3:1) 50%, P(4:0) 12.5% per leaf, worst of 2 leaves |
| all-to-all | L4 | 16 | ≈ 3.1–3.5 s | 64 flows per leaf; near even + work-conserving |

Overall prediction: job time tracks the busiest link, so job ≈ max-link bound
+ ≤ 0.3 s across all cells. Host container CPU stays far below the unshaped
≈ 1 core.

### Measured results (shaped)

Command: `.venv/bin/python -m fabric.experiments.e5_shaped run` on
2026-10-16 with `make fabric-shape-on` applied. Summary:
`python -m fabric.experiments.e5_shaped_report`. Raw:
[`e5-shaped-results.json`](e5-shaped-results.json). 36 cells: 2 patterns ×
{pinned, L3, L4} × {1, 16} flows/pair × 3 repeats. Max client start skew:
1.88 ms. **EMULATED + SHAPED 500 Mbit/s.**

- **Receiver job** is the measured job time: the latest receiver last-byte time
  over all pairs, from 0.1 s server intervals (upper edge, 0.1 s resolution),
  relative to T0.
- **Client-exit** is when the last iperf3 client process exited.
- **Gap vs pinned** is measured minus measured: the cell's mean receiver job
  minus the pinned (even-split) mean for the same pattern and flows/pair.
- **Max-link bound** is the busiest shaped link's TX bytes × 8 / 500 Mbit/s.

| Pattern | Routing | Flows/pair | Max/mean (r1/r2/r3) | Max-link bound s | Receiver job s (r1/r2/r3) | Mean | Gap vs pinned s | Client-exit s | TBF drops | Retx | Max host CPU cores | VM busy % |
|---|---|---:|---|---|---|---:|---:|---|---|---|---:|---:|
| ring | pinned | 1 | 1.000 / 1.004 / 1.003 | 3.03 / 3.03 / 3.03 | 3.30 / 3.30 / 3.30 | 3.30 | +0.00 | 4.01 / 4.01 / 4.01 | 60 / 39 / 49 | 97 / 58 / 70 | 0.17 | 16 |
| ring | pinned | 16 | 1.012 / 1.005 / 1.009 | 3.08 / 3.06 / 3.07 | 3.12 / 3.07 / 3.07 | 3.09 | +0.00 | 3.14 / 3.11 / 3.11 | 4525 / 4487 / 4103 | 4721 / 4645 / 4186 | 0.33 | 19 |
| ring | L3 | 1 | 1.996 / 1.996 / 1.996 | 6.05 / 6.06 / 6.06 | 6.20 / 6.20 / 6.10 | 6.17 | +2.87 | 7.01 / 7.01 / 7.01 | 110 / 129 / 163 | 127 / 140 / 175 | 0.12 | 13 |
| ring | L3 | 16 | 1.995 / 1.995 / 1.995 | 6.05 / 6.06 / 6.02 | 6.03 / 6.05 / 6.02 | 6.03 | +2.95 | 6.08 / 6.09 / 6.05 | 5814 / 5879 / 5923 | 5876 / 5934 / 5941 | 1.02 | 28 |
| ring | L4 | 1 | 1.996 / 1.996 / 1.996 | 6.06 / 6.02 / 6.07 | 6.10 / 6.01 / 6.10 | 6.07 | +2.77 | 7.01 / 6.03 / 7.01 | 142 / 116 / 134 | 155 / 121 / 215 | 0.13 | 13 |
| ring | L4 | 16 | 1.009 / 1.014 / 1.025 | 3.08 / 3.09 / 3.15 | 3.09 / 3.10 / 3.16 | 3.12 | +0.03 | 3.13 / 3.14 / 3.18 | 4129 / 4054 / 4095 | 4350 / 4192 / 4285 | 0.94 | 23 |
| all-to-all | pinned | 1 | 1.015 / 1.011 / 1.022 | 3.04 / 3.05 / 3.04 | 3.20 / 3.20 / 3.30 | 3.24 | +0.00 | 4.02 / 4.02 / 4.01 | 299 / 272 / 276 | 1333 / 1081 / 1132 | 0.39 | 25 |
| all-to-all | pinned | 16 | 1.003 / 1.019 / 1.012 | 3.12 / 3.12 / 3.12 | 3.21 / 3.21 / 3.33 | 3.25 | +0.00 | 3.29 / 3.44 / 3.37 | 8258 / 8061 / 8399 | 12416 / 11792 / 12088 | 1.76 | 44 |
| all-to-all | L3 | 1 | 1.501 / 1.500 / 1.501 | 4.56 / 4.56 / 4.56 | 4.80 / 4.70 / 4.70 | 4.74 | +1.50 | 5.02 / 5.01 / 5.02 | 451 / 519 / 480 | 1415 / 1896 / 1380 | 0.31 | 23 |
| all-to-all | L3 | 16 | 1.492 / 1.492 / 1.500 | 4.60 / 4.59 / 4.66 | 4.61 / 4.60 / 4.70 | 4.64 | +1.39 | 5.18 / 5.25 / 5.19 | 9025 / 8903 / 9268 | 12995 / 12781 / 12057 | 1.81 | 48 |
| all-to-all | L4 | 1 | 1.491 / 1.501 / 1.007 | 4.54 / 4.56 / 3.05 | 4.60 / 4.70 / 3.20 | 4.17 | +0.93 | 5.03 / 5.03 / 4.01 | 296 / 400 / 324 | 1440 / 1425 / 1289 | 0.36 | 24 |
| all-to-all | L4 | 16 | 1.015 / 1.008 / 1.015 | 3.16 / 3.15 / 3.16 | 3.31 / 3.21 / 3.30 | 3.27 | +0.02 | 3.37 / 3.35 / 3.39 | 8133 / 7234 / 7600 | 12243 / 11151 / 11143 | 1.57 | 45 |

Prediction vs measured:

| Pattern / routing / flows | Predicted | Measured receiver job (mean) | Verdict |
|---|---|---:|---|
| ring pinned 1, 16 | 3.1–3.3 s | 3.30, 3.09 s | as predicted |
| ring L3 1, 16 | ≈ 6–6.5 s, imbalance ≈ 2.0 | 6.17, 6.03 s; 1.996 / 1.995 | as predicted; flows/pair gave no help with L3 |
| ring L4 1 | 3 or 6 s per repeat, mostly 6 | 6.10 / 6.01 / 6.10 s (imbalance 1.996 all three) | collision in all 3 repeats (predicted P = 75% each) |
| ring L4 16 | 3.1–3.6 s | 3.12 s (gap +0.03 s vs pinned) | as predicted: work-conserving, ≈ even split |
| all-to-all pinned 1, 16 | 3.1–3.3 s | 3.24, 3.25 s | as predicted |
| all-to-all L3 1, 16 | ≈ 4.5 s (3:1) | 4.74, 4.64 s; imbalance 1.49–1.50 | as predicted (3:1 split) |
| all-to-all L4 1 | 3–6 s, most likely 4.5 | 4.60 / 4.70 / 3.20 s | as predicted (two 3:1 repeats, one 2:2) |
| all-to-all L4 16 | 3.1–3.5 s | 3.27 s (gap +0.02 s) | as predicted |
| job ≈ max-link bound + ≤ 0.3 s | — | receiver job − bound: −0.02 … +0.27 s over 36 cells; Pearson r(job, bound) = 0.998 | **job time tracks max-uplink load** |
| host CPU far below 1 core | — | max container 0.12–1.81 cores; VM 13–48% busy | lower than unshaped, but not "far below" at 16 flows all-to-all (1.8 cores in one container) |

Findings:

1. **With the uplinks as the bottleneck, ECMP imbalance shows up directly in
   job time.** Ring with L3 (or with L4 at one flow per pair) puts both of a
   leaf's pairs on one uplink. The measured job is about 2× the measured
   even-split baseline: +2.77 to +2.95 s on a 3.1–3.3 s job. All-to-all with
   L3 splits 3:1, which costs +1.39 to +1.50 s (+43–46%).
2. **Many flows per pair recover almost all of it under L4.** The gap at
   16 flows is +0.02/+0.03 s against the pinned baseline. A pair whose streams
   use both uplinks keeps both links busy until it finishes, so the residual
   per-flow imbalance (1.01–1.03) barely matters. With L3, 16 flows recovered
   nothing.
3. **The unshaped "imbalance-implied bound" did not predict anything; this
   rerun's measured bound does.** Here the busiest link's bytes ÷ link rate
   matches measured job time within 0.27 s in every cell (Pearson r = 0.998),
   and the even-split baseline is a measured execution.
4. **The measurement fix mattered.** iperf3's own completion values snap to
   whole seconds for single-stream tests. Client exit was 4.01 s where the
   receiver's last byte arrived at 3.30 s, and `sum_received.seconds` read
   1.0014 s for a 0.32 s transfer in a check run. The first shaped run used
   client exit and is kept as [`e5-shaped-results-run1.json`](e5-shaped-results-run1.json)
   with the same imbalance/bound values. Its single-flow job times are
   ≈ 1 s high for this reason.

Failures diagnosed during this rerun:

- **One-way pins broke replies.** Symptom: pinned ring iperf3 server timed
  out; `ping` host2→host4 failed with pins installed and worked without them.
  Evidence: the echo request left via spine2 and the reply arrived on leaf1 from
  spine1 and was dropped; `nstat TcpExtIPReversePathFilter` on leaf1 rose by 2
  per ping. An `iif`-restricted rule did not help. Cause: leaf1's
  reverse-path check consults the pin rule for the reply's (src, dst), which
  points at the other uplink. Fix: pin **both directions of each host pair to
  the same spine** (`fabric/render/shaping.py:pin_assignment`, tested in
  `test_shaping.py`).
- **Editing the intent during a run crashed it.** `background()` re-loads the
  intent on every call, so a mid-run edit that briefly failed schema
  validation stopped the first attempt after 12 cells. It was resumed with
  `--resume`; afterwards the intent was frozen during runs.
