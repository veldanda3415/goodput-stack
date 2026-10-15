# E1 — Linux ECMP hash policy

**Status:** measured 2026-10-15; all results are EMULATED (veth links and Linux
kernel forwarding, not a switch ASIC and not line-rate contention).

## Setup and method

The experiment sends TCP traffic from host1 rail A (`10.210.0.2`) to host3 rail
A (`10.210.0.10`), through leaf1 to leaf2 across the two spine uplinks. It uses
`iperf3 -P 1`, `-P 4`, and `-P 32`, for 10 seconds and 3 repeats per point,
under `net.ipv4.fib_multipath_hash_policy=0` (L3) and `=1` (L4). The Python
driver is run with `make fabric-e1`.

The split is measured from the source leaf's per-uplink transmitted byte
counters: `ip -j -s link show dev eth1` and `eth2`, read before and after each
iperf3 run. The driver records both raw counter values and deltas, percentages,
iperf3 summaries, the version, and any gateway-probe wait in
[`e1-results.json`](./e1-results.json). The gateway probe guard is checked
before each run; if one is active, the driver waits and polls every 60 seconds
for at most 20 minutes.

Linux 6.18 keeps `fib_multipath_hash_policy` in `struct netns_ipv4` and
registers the sysctl per network namespace, so the driver sets and reads back
the policy independently inside each leaf's namespace:
[netns IPv4 structure](https://github.com/torvalds/linux/blob/v6.18/include/net/netns/ipv4.h),
[IPv4 sysctl registration](https://github.com/torvalds/linux/blob/v6.18/net/ipv4/sysctl_net_ipv4.c).

## Predictions (written before running the experiment)

The percentages below are eth1/eth2. Under L3 hashing, source/destination IPs
are identical across parallel TCP streams, so all streams from this fixed host
pair are predicted to use one uplink. Under L4 hashing, one stream still maps
to one uplink; with multiple source ports, the predicted aggregate is an even
split. With one flow, either uplink may win.

| Hash policy | Parallel flows | Predicted eth1/eth2 split |
|---|---:|---|
| L3 (`0`) | 1 | 100/0 or 0/100 |
| L3 (`0`) | 4 | 100/0 or 0/100 |
| L3 (`0`) | 32 | 100/0 or 0/100 |
| L4 (`1`) | 1 | 100/0 or 0/100 |
| L4 (`1`) | 4 | 50/50 |
| L4 (`1`) | 32 | 50/50 |

## Measured results

Command: `make fabric-e1`. Each cell below has three measured repeats. The
percentages are computed solely from the source leaf's `eth1` / `eth2` TX-byte
counter deltas; the exact before/after counters and byte deltas are in
[`e1-results.json`](./e1-results.json).

| Hash policy | Flows | Prediction | Measured eth1/eth2 split (%) repeats 1 / 2 / 3 |
|---|---:|---|---|
| L3 (`0`) | 1 | 100/0 or 0/100 | 0.00/100.00; 0.00/100.00; 0.00/100.00 |
| L3 (`0`) | 4 | 100/0 or 0/100 | 0.00/100.00; 0.00/100.00; 0.00/100.00 |
| L3 (`0`) | 32 | 100/0 or 0/100 | 0.00/100.00; 0.00/100.00; 0.00/100.00 |
| L4 (`1`) | 1 | 100/0 or 0/100 | 100.00/0.00; 0.00/100.00; 0.00/100.00 |
| L4 (`1`) | 4 | 50/50 | 75.33/24.67; 50.24/49.76; 75.41/24.59 |
| L4 (`1`) | 32 | 50/50 | 49.32/50.68; 36.92/63.08; 52.83/47.17 |

For example, in the three L3 / 1-flow runs the raw `eth1/eth2` TX-byte deltas
were `11565/10452378246`, `11401/9664627610`, and `11850/9699738716`. The
remaining raw counter values are retained per run in the JSON artifact.
`iperf3` sent/received byte and rate summaries are also retained there as
traffic context, not as the source for the split calculation. All 18 planned
runs had zero gateway-probe wait, and the driver restored the leaf hash policy
to `0`.

During driver development, two failures occurred before traffic (multiple
hosts on a leaf made the first selection ambiguous; then containerlab returned
the sysctl readback as an integer). A subsequent 10-second L3 / 1-flow trial
transferred traffic but was excluded when the runner incorrectly expected the
JSON-decoded iperf output to be a string. The parser was corrected, and the
complete 18-run sweep above then finished successfully.

## Interpretation

ECMP selects one next hop for a flow; it does not stripe individual packets
across both links. Hash policy changes which packet fields feed the selection,
not the one-next-hop-per-flow behavior. With L3 hashing, every TCP stream
between this same source/destination IP pair has the same L3 key and is
predicted to land on the same uplink. L4 hashing can distinguish streams by
their transport ports. The single-flow repeats selected one uplink each time;
the four-flow sample varied from about 50/50 to about 75/25, while the
32-flow sample was closer to an even split but still varied between repeats.

AI collectives with a few long-lived elephant flows between fixed GPU pairs
can therefore leave one uplink hot while another is underused. This experiment
shows only Linux kernel hash behavior with veths; ASIC hash fields, resilient
hashing, queueing, buffers, PFC, line rate, and production contention are not
measured.
