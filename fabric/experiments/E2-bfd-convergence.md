# E2 — BFD convergence

**Status:** complete; EMULATED (containerlab veth links and Linux kernel
forwarding; no ASIC or production timing claims).

## Setup and method

The source is host1 rail A (`10.210.0.2`); the target is host3 rail A
(`10.210.0.10`). Before the failure trials, the driver sends a two-second ping
and chooses the leaf1 uplink with the largest increase in TX-byte counters.
It resolves that interface to its spine through the intent. This avoids
assuming that the ICMP flow hashes to the same path as E1's TCP flow.

Each trial runs a 15-second high-rate ICMP stream
(`ping -D -n -i 0.01 -w 15`) and injects the fault after 1 second. This uses
ping, not iperf3, so no iperf3 run is longer than 10 seconds. There are three
repeats for each combination of BFD on/off and fault type:

* **Carrier down:** `ip link set dev eth1 down` inside spine2; the link is
  restored after the ping run.
* **Silent loss:** `tc qdisc replace dev eth2 root netem loss 100%` on leaf1
  and `tc qdisc replace dev eth1 root netem loss 100%` on spine2. Applying
  netem at both ends drops both directions while `LOWER_UP` remains present.
  The qdiscs are removed after the ping run.

The BFD-on settings come from intent: 100 ms transmit/receive and detect
multiplier 3; the BGP hold timer is 9 seconds. For BFD-off trials, BFD is
removed from leaf1's shared fabric peer group and both corresponding spine
peer groups, so neither the failed path nor the backup path uses BFD. The
surviving BGP adjacency continues to carry traffic; the failed adjacency can
only expire by its BGP hold timer. The driver uses FRR's `no neighbor <group>
bfd` command for removal and reinstalls the configured `bfd profile FABRIC`
when restoring BFD.

The driver checks for active gateway probes before each trial, verifies BGP
adjacencies before and after faults, records link/BFD state during the fault,
and waits for reconvergence before the next repeat. It persists each measured
trial and raw timing in [`e2-results.json`](./e2-results.json). FRR behavior is
based on the pinned 10.2 documentation for
[BGP](https://docs.frrouting.org/en/stable-10.2/bgp.html) and
[BFD](https://docs.frrouting.org/en/stable-10.2/bfd.html).

The first pilot used the TCP-selected E1 link without measuring the ICMP path.
It completed the six BFD-on trials but stopped before BFD-off runs. Its
measurements are preserved in [`e2-pilot-results.json`](./e2-pilot-results.json)
and excluded from the final comparison. The pilot also exposed a BFD-off
configuration mistake: `no neighbor FABRIC bfd profile FABRIC` removed the
profile but left `neighbor FABRIC bfd` active. FRR's running config and BFD
peer JSON still showed BFD up, and the driver's off-mode check timed out. The
driver now removes BFD with `no neighbor <group> bfd` and verifies the peer
sessions are absent before starting the off-mode trials.

A second pilot measured the ICMP path (leaf1:eth2 to spine2:eth1) and confirmed
the corrected BFD-off command removed the BFD peers. It then timed out waiting
for the failed BGP adjacency to recover after the last BFD-on fault: the mode
transition began before that final adjacency was established. The six
path-verified BFD-on runs are preserved in
[`e2-pilot-path-results.json`](./e2-pilot-path-results.json) and excluded from
the final comparison. The driver now waits for all BGP/BFD adjacencies to
recover before switching modes, and also waits for BGP recovery after the last
BFD-off trial before restoring BFD.

A complete 12-trial calibration run is also preserved as
[`e2-timing-calibration-results.json`](./e2-timing-calibration-results.json)
but excluded from the comparison. Inspection showed that the driver started
the fault clock only after fault injection completed, which omitted the
failover interval while the qdiscs or carrier state were being changed. The
current driver timestamps immediately before injection and includes the full
transition.

## Results

Run `make fabric-e2` to populate the data. The estimated loss window uses the
reply gap with the most skipped sequence numbers during the fault, minus the
median pre-fault reply interval; sequence numbers give the number of missed
probes in that gap. `lost_probe_count_during_fault` sums skipped sequence
numbers over all reply gaps during the fault.
`fault_to_recovery_ms` is the time from fault application until the first
successful reply after a gap containing lost probes. These are computed from
`ping -D` reply timestamps and sequence numbers, not inferred from the
BGP/BFD timers.

| Fault | BFD | Repeat 1 | Repeat 2 | Repeat 3 |
|---|---|---:|---:|---:|
| Carrier down | On | 0 / 0 ms (0) | 0 / 0 ms (0) | 0 / 0 ms (0) |
| Carrier down | Off | 0 / 0 ms (0) | 0 / 0 ms (0) | 0 / 0 ms (0) |
| Silent loss | On | 488 / 1012 ms (29) | 568 / 1075 ms (30) | 516 / 1009 ms (30) |
| Silent loss | Off | 7356 / 7868 ms (434) | 8412 / 8968 ms (500) | 9144 / 9685 ms (540) |

Cells show **estimated loss window / time to first reply after loss (missed
probes)**. Values are rounded to whole milliseconds. Carrier-down trials had
no sequence gaps and no packet loss; their largest reply gap was about 20 ms
against a 16 ms median baseline, so no outage window was observed. The ICMP
path probe selected leaf1:eth2 to spine2:eth1 from TX-byte deltas (14,457 vs
2,599 bytes; 121/121 replies). The gateway-probe guard waited 0 seconds for
all 12 trials.

## Interpretation

An administrative carrier-down is immediately visible to the directly
connected Linux interface, so the kernel and FRR can withdraw that path even
with BFD disabled. BFD's purpose is clearest for a silent loss: carrier stays
up, but BFD detects missing control packets at its configured detection time;
without BFD, the BGP hold timer is the fallback.

In these runs, silent-loss recovery with BFD was about 1.01–1.08 seconds to
the first reply after loss, with estimated lost-reply windows of 0.49–0.57
seconds. With BFD disabled, the first reply returned after 7.87–9.68 seconds
and estimated loss windows were 7.36–9.14 seconds, consistent with waiting
for the configured 9-second BGP hold timer. These are observations from this
emulated environment, not predicted or guaranteed switch timings.

These are simulated veth and Linux-kernel timings. They do not measure ASIC
link-fault detection, switch forwarding, congestion, buffers, PFC, or
production convergence.
