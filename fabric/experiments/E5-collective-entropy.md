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
