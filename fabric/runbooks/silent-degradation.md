# Silent degradation: "step time +30%, no errors"

**Label: MEASURED-IN-LAB (EMULATED, shaped)**: evidence in
[E6](../experiments/E6-failure-drills.md#silent-degradation-finding-it-without-being-told)
and panel exports [`e6-degrade-panels-r1.json`](../telemetry/e6-degrade-panels-r1.json)
… `-r3`. The fault was 1% random loss (`netem`) on one leaf uplink, link up,
no BGP/BFD event. The lab has no FCS/FEC counters; see
[`fec-crc-errors.md`](fec-crc-errors.md) for the hardware equivalent.

## Symptom

Training step time rises with no alarms: links up, BGP/BFD stable, no
interface errors. In E6 run 1 the job slowed **+85%** (step-equivalent
20.7 → 38.4 s). The two ring pairs whose flows used the lossy uplink fell from
≈ 470 to 251–272 Mbit/s. In runs 2–3 the same 1% loss cost ≈ 4% or nothing
measurable: with 16 flows per pair, TCP kept the shaped link full.

## Signals (dashboard row "EMULATED silent degradation signals")

| Signal | PromQL | Run 1 (lossy leaf1:eth1) |
|---|---|---|
| Uplink share of its leaf | `rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]) / on (node) group_left sum by (node) (rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]))` | 0.50 → **0.094** (sibling 0.906) |
| Root-qdisc drops per MB, vs ECMP sibling | `rate(fabric_qdisc_drops_total{node=~"leaf[1-4]"}[1m]) / (rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]) / 1e6)` | 17.3 vs 2.08 (**8.3×**) |
| Host TCP retransmit ratio | `rate(fabric_host_tcp_retrans_segments_total[1m]) / rate(fabric_host_tcp_out_segments_total[1m])` | host1/host2 peaked at 5.0% / 3.3% (≈ 1% before) → the senders behind leaf1 |
| BGP/BFD, link state | `fabric_bgp_neighbor_established`, `fabric_bfd_peer_up` | unchanged: that is what makes it "silent" |

## Isolate (without knowing the link)

1. Confirm it's the network: step time up, but GPU/host metrics normal.
   Compare host TCP retransmit ratios: the hosts whose flows cross the bad
   link stand out (run 1: host1/host2).
2. Per leaf, compare each uplink with its ECMP sibling. A member whose
   **share falls** or whose **drops per MB rise** well above its sibling is
   the suspect. Siblings should be near-identical under a many-flow L4 hash
   (E5: max/mean 1.01–1.03).
3. Confirm with a direct test before acting: drain the suspect (shut it or
   raise its cost) and watch step time and retransmits. On hardware, read the
   receiver's FCS/FEC counters for that port.

**Measured detection rate in the lab:** drops/MB found the right uplink in
2 of 3 runs (run 2's margin was only 1.8×), and uplink share in 1 of 3. The
1% loss sat in the same range as the shaped links' normal congestion drops
(2–4 per MB), and Linux counts a dropped GSO super-packet as one drop. Treat
these signals as *suspects*, not proof.

## Remediate

- Drain the link (shut/cost-out) and repair the optic, cable, or port; return
  it only after a clean soak period.
- If the job can't wait: drain first. ECMP on the remaining member is fast
  (E6 link-down: FIB updated in < 0.3 s), but capacity halves for that leaf.

## Verify

Uplink shares back to ≈ 0.5, drops per MB back in line with the sibling, host
retransmit ratio back to baseline, step time back to baseline (E6 pre-fault ≈ 20.7 s).

## Prevent

- Alert on **relative** signals (member vs sibling share, drops per MB,
  retransmit ratio by host) and on step-time regressions, not only on link down.
- In production, add receiver-side error counters (FCS/CRC, FEC uncorrectable)
  and active per-path probing (many small probes per ECMP member, or
  per-flow retransmit attribution by 5-tuple → path). The lab lacks the
  former and has not implemented the latter.
- Keep flow entropy high (16 flows/pair). It made 1% loss nearly harmless in 2
  of 3 runs, at the cost of making the fault harder to find.
