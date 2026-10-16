# E6 — Failure drills under collective load

**Label: EMULATED, SHAPED.** veth + Linux forwarding + FRR 10.2.1 BGP/BFD,
leaf↔spine links TBF-shaped to 500 Mbit/s per direction (`lab_shaping`,
[E5 shaped rerun](E5-collective-entropy.md#shaped-uplinks-rerun)). Faults are
injected with `ip link` and `tc netem` inside the lab containers. Reconvergence
numbers are Linux/FRR software timings on one WSL2 VM, not switch ASIC
failover times.

## Method

`python -m fabric.experiments.e6_drills all` (`make fabric-e6`). Raw:
[`e6-results.json`](e6-results.json).

- **Load:** E5-style ring over the four rail-A hosts (host1→host3→host2→host4→host1),
  L4 hash, 16 flows/pair, `iperf3 -t 30 -i 0.5`, synchronized start (T0). The
  receiver timeline comes from 0.5 s server intervals
  (`iperf3 -s -i 0.5 -J`, `--get-server-output`), per pair and per stream.
- **Collective step time:** the time at which the *slowest* ring pair has
  received W bytes. W is the baseline's mean slowest-pair bytes at T0+20 s, so
  a fault-free step takes about 20 s. A ring collective advances at the pace
  of its slowest pair.
- **In parallel:** `ping -D -i 0.1` probes, one per rail and per tenant:
  rail A host1→host3 (crosses leaf1 uplinks), rail B host1→host3 (leaf3→leaf4),
  rail A host3→host4 (same leaf2), ta1→ta3, tb1→tb4, tb2→tb4. Plus
  `ip -ts monitor route nexthop` on leaf1/leaf2/leaf3 for kernel FIB change
  timestamps, and BGP/BFD state after each run.
- **Timing:** fault at T0+10 s, restore at T0+20 s. Flap runs T0+5 → T0+25 s.
  Silent degradation runs for 150 s with the fault from T0+70 s, so
  Prometheus's 1-minute rate windows cover both a clean window and a fault
  window. (The prediction table below was written with a 90 s / T0+20 s plan.
  The window was lengthened before running, so that a full 1-minute
  pre-fault window existed.)
- **After every run:** restore from the rendered scripts, then wait until all
  16 BGP sessions are Established and all BFD peers are up (that wait is
  recorded). After every fault type: `make fabric-test`.

## Predictions (written before the runs)

| Fault | How | Predicted blast radius | Predicted detection / recovery | Predicted step-time impact |
|---|---|---|---|---|
| Leaf–spine link, carrier down | `ip link set eth1 down` on spine1 (spine1↔leaf1) | Streams hashed onto spine1↔leaf1 in both directions; leaf1 left with one 500 Mbit/s uplink for two ring pairs (need 1 Gbit/s). Rail B, same-leaf rail A, tb2→tb4 untouched | Carrier loss → zebra removes the nexthop in < 0.1 s; per-stream stall ≤ 1 s (in-flight loss + TCP RTO). After `up`, BGP unnumbered re-establishes in a few seconds | leaf1 pairs at ~50% for 10 s → step +≈5 s (≈ +25%) |
| Silent loss (carrier up) | `tc netem loss 100%` both ends of spine1↔leaf1 | Same streams as above | BFD 3 × 100 ms → ≈ 0.3 s detection, then BGP down; loss window ≈ 0.3–1 s. Recovery after restore may be slow: F1 saw FRR's 120 s BGP connect-retry | ≈ +5 s, plus extra time on one uplink if re-establishment is slow |
| Link flap | down 2 s / up 2 s × 5 | Same streams, repeatedly | If BGP takes > 2 s to re-establish, the link never rejoins ECMP and the flap behaves like a 20 s outage with 5 short loss bursts. No dampening configured | ≈ +10 s (half rate for leaf1 pairs for 20 s) |
| Spine loss | all spine1 fabric links down | Every cross-leaf flow through spine1, all leaves; fabric capacity halves. Same-leaf traffic untouched | Carrier → immediate withdrawal on all leaves; brief loss for spine1 streams | All four ring pairs at ~50% for 10 s → ≈ +5 s |
| Leaf loss | every leaf1 data port down | host1 + host2 lose **rail A** entirely; vmhost1 loses its only NIC; ta1 and tb1 lose the front end. Their rail B (via leaf3), host3↔host4, tb2→tb4 stay up | Immediate for neighbors. After restore, TCP waits on exponential RTO backoff (several seconds) and BGP re-establishes | Ring stalls completely: two of four pairs stop, and a ring collective can't advance → ≥ +10 s, likely +12–17 s with RTO backoff |
| Silent degradation | `netem loss 1%` (rate kept 500 Mbit/s) on ONE leaf uplink, chosen at random by the runner and not looked at until detection | Streams on that uplink only; no BGP/BFD/link event | Nothing in BGP/BFD. Should be visible as (1) that uplink's TX share falling against its ECMP sibling, (2) a rise in host TCP retransmits, (3) root-qdisc drops relative to bytes on that port | 1% loss caps TCP cwnd (Mathis: rate ∝ MSS/(RTT·√p)), so affected streams slow sharply. Step time +10–40% |

## Results

Run on 2026-10-16, 13:15–13:57 EDT: `python -m fabric.experiments.e6_drills all --verify`,
with `make fabric-shape-on`, L4 hash on leaves, and telemetry up
(`make telemetry-up`). Summary: `python -m fabric.experiments.e6_report`.
Raw: [`e6-results.json`](e6-results.json). 21 runs: 3 baseline + 6 faults × 3.
**EMULATED, SHAPED 500 Mbit/s.** Baseline: W = 1.204 GB, baseline step
19.89 / 20.15 / 19.97 s (mean 20.00 s), no probe loss in any baseline run.

### Step time, stalls, reconvergence

"FIB first change" is the first `ip -ts monitor route nexthop` event on leaf1
(leaf2 for leaf loss) after the fault command. "Last FIB change after restore"
is when the last route/nexthop update landed after the restore command, i.e.
when ECMP was whole again. ">30 s (x% of W)" means the slowest pair had not
received W bytes when the 30 s run ended.

| Fault | Step time s (r1 / r2 / r3) | Δ vs baseline | Longest stream stall s | Streams stalled ≥ 1 s (of 64) | FIB first change after inject s | Last FIB change after restore s |
|---|---|---|---|---|---|---|
| baseline | 20.15 / 19.89 / 19.97 | — | 0 / 0.5 / 0.5 | 0 / 0 / 0 | — | — |
| link down (carrier) | 27.40 / 29.10 / 28.13 | +7.4 / +9.1 / +8.1 s (+37–46%) | 3.0 / 3.5 / 1.5 | 22 / 28 / 22 | 0.264 / 0.260 / 0.246 | 3.66 / 5.11 / 3.45 |
| silent loss (netem 100%) | 27.11 / 27.76 / 28.29 | +7.1 / +7.8 / +8.3 s (+36–41%) | 2.0 / 1.0 / 7.5 | 8 / 3 / 10 | 0.574 / 0.537 / 0.551 | 2.44 / 2.55 / 2.39 |
| flap (5 × 2 s down/up) | >30 (89%) / >30 (93%) / >30 (90%) | > +10 s | 1.5 / 3.5 / 4.5 | 19 / 27 / 23 | 0.276 / 0.280 / 0.279 | 1.64 / 1.80 / 2.20 (after the last up) |
| spine loss | >30 (99%) / >30 (75%) / 28.92 | ≥ +8.9 s | 3.5 / 3.0 / 3.0 | 43 / 37 / 39 | 1.444 / 0.276 / 0.346 | 5.79 / 4.64 / 3.79 |
| leaf loss | >30 (71%) / >30 (67%) / >30 (69%) | ring stalled for the fault + ≈ 3.4 s | 19.5 / 19.0 / 19.0 | 64 / 64 / 64 | 0.337 / 1.109 / 0.360 (leaf2) | 3.49 / 4.23 / 3.27 |

All four ring pairs ran at ≈ 230–270 Mbit/s (half of 500) during every
single-link fault, not only the two leaf1-sourced pairs. Traffic *into*
leaf1 also lost its spine1 path, because spine1 has one link per leaf. Leaf loss
dropped every pair to ≈ 10 Mbit/s (≈ 40–49 in r2): the ring collective
cannot advance when two of its four members are cut off.

After every run all 16 BGP sessions and BFD peers were up within
2.7–4.6 s of the run ending. `make fabric-test`-equivalent pytest ran after each fault
type: **61 passed** each time. The "4 failed" in those records are the
four NX-OS renderer unit tests (`test_nxos_render.py`), added to the working tree
during E6 and failing with `KeyError: 'fabric_p2p'` until the intent gained
the /31 pool; they test no lab state.

### Blast radius (ping probes, 0.1 s interval): lost replies (longest gap, when)

"inj" = during the fault, "rst" = after the restore command.

| Fault | rail A host1→host3 (leaf1→leaf2) | rail B host1→host3 (leaf3→leaf4) | rail A host3→host4 (same leaf2) | tenant-a ta1→ta3 (leaf1→leaf3) | tenant-b tb1→tb4 (leaf1→leaf4) | tenant-b tb2→tb4 (leaf2→leaf4) |
|---|---|---|---|---|---|---|
| link down | 1 (0.1 s inj) ×3 | 0 | 0 | 1 (0.1 s inj) ×3 | 11 / 16 / 8 (0.6–1.2 s **rst**) | 0 |
| silent loss | 10 / 7 / 8 (0.6–0.7 s inj) | 0 | 0 | 7 / 6 / 6 (0.5–0.6 s inj) | 7 / 6 / 7 (0.6 s inj) | 0 |
| flap | 3 / 1 / 1 (0.1 s) | 0 | 0 | 1 ×3 (0.1 s) | 15 / 24 / 18 (0.6–1.2 s) | 0 |
| spine loss | 14 / 11 / 12 (1.1–1.5 s **rst**) | 11 / 26 / 18 (1.2–2.7 s **rst**) | 0 | 2 / 4 / 7 (≤ 0.5 s rst) | 5 / 17 / 11 (0.4–1.5 s rst) | 13 / 14 / 10 (1.0–1.4 s rst) |
| leaf loss | 51 / 50 / 47 (13.0–13.3 s) | **0** | 0 | 51 / 49 / 47 (13.0–13.4 s) | 49 / 52 / 47 (13.0–13.3 s) | **0** |

### Prediction vs measured

| Fault | Predicted | Measured | Verdict |
|---|---|---|---|
| link down | leaf1 pairs at half rate, step +≈ 5 s, stall ≤ 1 s, BGP back in a few s | **all four** pairs at half rate (both directions of the leaf1↔spine1 link), step +7.4–9.1 s; FIB change 0.25–0.26 s after carrier loss; rail probes lost 1 packet; 22–28/64 streams stalled 1.5–3.5 s (TCP RTO backoff); ECMP whole 3.5–5.1 s after link up | detection as predicted; impact larger (both directions); **the longest tenant-b loss (0.6–1.2 s) came on restore**, not on failure |
| silent loss | BFD ≈ 0.3 s, loss 0.3–1 s; possibly slow recovery (F1's 120 s connect-retry) | loss 0.5–0.7 s on every probe through the link; first FIB change 0.54–0.57 s; ECMP whole 2.4–2.6 s after restore; **no 120 s wait** | as predicted for detection; recovery much faster than feared: BFD-down does not leave the interface-peer session in a long connect-retry here |
| flap | link never rejoins; ≈ +10 s | step > 30 s in all repeats (89–93% of W at 30 s); per-flap rail loss ≤ 0.1 s; 19–27 streams stalled; tenant-b lost up to 24 probes | as predicted: repeated reconvergence costs more than one clean outage |
| spine loss | all pairs ~50%, ≈ +5 s, brief loss | step ≥ +8.9 s; 37–43 of 64 streams stalled; every cross-spine probe on **both rails and both tenants** lost 1.0–2.7 s **after restore** (T0+24 s ≈ 4 s after links up); only same-leaf traffic untouched | blast radius as predicted; the **restore transient** was not predicted (see below) |
| leaf loss | rail A of host1/host2, vmhost1, ta1, tb1 lose service; ring stalls; +12–17 s | every leaf1-attached probe lost 13.0–13.4 s (10 s fault + ≈ 3.3 s recovery); ring progress ≈ 10 Mbit/s per pair during the fault; **rail B host1→host3 and tb2→tb4 lost nothing** | as predicted |
| silent degradation | +10–40%; visible in share, drops, retransmits | see next section: one of three runs +85%, the others ≈ +4% / not measurable; signals found the link 2/3 (drops) and 1/3 (share) | partially; prediction too confident |

**Restore is the dangerous moment.** The largest loss windows for link-down
(tenant-b), flap, and spine-loss came 2–4 s *after* the link came back, when
BGP re-established and the returning path re-entered ECMP. The likely
mechanism (**hypothesis, not verified in this run**): a leaf installs the
returning spine as an ECMP next hop as soon as its own session to that spine
is up, before the spine has learned routes from every other leaf, so some
hashed flows briefly hit a spine without the route. FRR mitigations to test
next: `bgp update-delay` / `bgp max-med on-startup` on spines, or holding the
link out of ECMP until the spine has a full table.

### Silent degradation: finding it without being told

Each run picked one of `leaf1:eth1, leaf1:eth2, leaf2:eth1, leaf2:eth2` at
random (seed recorded) and replaced its TBF with `netem loss 1% rate
500mbit limit 1000`. Ring load ran for 150 s with the fault from T0+70 s. The
runner then queried Prometheus over a pre-fault window (1-minute rates
ending at injection) and a fault window (ending at T0+145 s), picked a suspect
from the telemetry, and only then wrote the injected port into the record.

Queries (also dashboard row "EMULATED silent degradation signals"):

```promql
# (A) drops per MB sent, compared with the ECMP sibling
rate(fabric_qdisc_drops_total{node=~"leaf[1-4]"}[1m])
  / (rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]) / 1e6)
# (B) uplink share of its leaf's TX
rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m])
  / on (node) group_left sum by (node) (rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m]))
# (C) host TCP retransmit ratio
rate(fabric_host_tcp_retrans_segments_total[1m]) / rate(fabric_host_tcp_out_segments_total[1m])
```

| Run | Injected (revealed after) | Suspect by (A) drops/MB vs sibling | Suspect by (B) share change | Impact (same run, step-equivalent at slowest pair's rate, pre → fault) |
|---|---|---|---|---|
| 1 | leaf1:eth1 | **leaf1:eth1** (17.3 vs 2.08 drops/MB, 8.3×) | **leaf1:eth1** (0.50 → 0.094) | 20.7 → 38.4 s (**+85%**); host1→host3 and host2→host4 fell to 272 / 251 Mbit/s; host1/host2 retransmit ratio peaked at 5.0% / 3.3% |
| 2 | leaf2:eth1 | **leaf2:eth1** (3.14 vs 1.78, 1.8×: weak) | leaf1:eth1 (miss; shares unchanged at 0.50) | 21.9 → 22.8 s (+4%) |
| 3 | leaf2:eth2 | leaf2:eth1 (miss) | leaf1:eth2 (miss) | not measurable: pair rates already uneven before the fault (322–637 Mbit/s), so pre/fault step-equivalent was 29.9 → 22.6 s |

Panel exports over each run's window (like F4's E5 export):
[`../telemetry/e6-degrade-panels-r1.json`](../telemetry/e6-degrade-panels-r1.json),
[`-r2`](../telemetry/e6-degrade-panels-r2.json), [`-r3`](../telemetry/e6-degrade-panels-r3.json).

What this shows:

1. **When 1% loss bites, it is easy to find.** In run 1 the lossy uplink's
   share collapsed from 0.50 to 0.09 while its drops/MB rose 8×. Both signals
   pointed at it, and the job slowed 85% with no link, BGP, or BFD event.
   That is the "step time +30%, no errors" case.
2. **When it doesn't bite, it hides.** In runs 2–3 the lossy link still carried
   a full 62 MB/s. With 16 flows per pair, TCP filled the shaped link despite
   1% random loss. The lab's TBF congestion drops (2–4 per MB on every busy
   uplink) are the same order as the injected loss. Linux counts a dropped
   GSO super-packet as one drop, so (A) under-counts netem loss on veth.
   The step-time impact was small or below the noise of pair-to-pair TCP
   unfairness.
3. **Production needs receiver-side error counters or active probing.** On
   hardware the equivalent fault shows up as FCS/CRC or FEC-uncorrectable
   counts on the receiving port ([`../runbooks/fec-crc-errors.md`](../runbooks/fec-crc-errors.md)).
   The lab has no such counter. Next step: per-uplink active probes (many
   small packets per ECMP member) or per-flow retransmit attribution
   (`ss -ti` 5-tuples → `ip route get … sport/dport` on the source leaf).

Verdict on "show how to find it": **partially achieved**. The query set found
the link in 2 of 3 runs, but only run 1 had a clear margin. Recorded as such.
