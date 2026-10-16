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
Tested later: see [Restore transient (#32)](#restore-transient-32). The
hypothesis as worded is refuted; the black hole on the spine is confirmed.

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

## Restore transient (#32)

**Label: EMULATED, SHAPED 500 Mbit/s.** Issue #32: in the spine-loss drill
every cross-spine probe lost 1.0–2.7 s about 4 s *after* spine1's links came
back, more than at the failure. This section tests the hypothesis above.

### Method

`python -m fabric.experiments.e6_restore --repeats 3 --label before`
([`e6_restore.py`](e6_restore.py)). Raw:
[`e6-restore-results.json`](e6-restore-results.json). Same spine-loss drill
as above (spine1 eth1–eth4 down at T0+10 s, up at T0+20 s; ring load, L4
hash, six ping probes at 0.1 s). Added, on one clock (Unix time; the
containers share the host kernel clock and print UTC, parsed as UTC):

- `ip -ts monitor link route nexthop neigh` on spine1 and leaf1–4: link up,
  kernel route and nexthop changes, neighbor (ND) entries;
- a 10 Hz poller in the same five nodes: BGP state and `pfxRcd` per session,
  BFD status per peer, and the kernel's BGP routes grouped by next-hop
  device (`ip -4 route show proto bgp`);
- every ping reply timestamp, so a loss window is the exact reply gap.

### Prediction (written before the runs)

If the hypothesis holds, each run's timeline reads: links up → BFD up → BGP
Established on leafN↔spine1 (sessions come up at different times) → leafN
installs spine1 (`eth1`) as an ECMP next hop for remote prefixes **while
spine1's `pfxRcd` from some other leaf is still 0** → probe loss starts →
loss ends when spine1 has prefixes from all four leaves and has them in its
FIB. Loss would start ≈ 3–4 s after link up and last 1–3 s, as before.

What would refute it: loss that starts before any leaf has a route via
spine1, or that continues after spine1 has every leaf's prefixes installed.
A caveat I expect to matter: with eBGP a leaf can only learn prefix P via
spine1 once spine1 has P, so a pure "spine has no route" black hole should
be impossible at the control-plane level. If loss appears anyway, the gap is
more likely between spine1's RIB and its kernel FIB (zebra programming) or
in neighbor resolution of the IPv6 link-local next hop (RFC 5549), which the
neighbor and route monitors would show.

### Results (2026-10-16, 15:18–15:23 EDT, runs 901–903)

Log: [`e6-restore-before.log`](e6-restore-before.log); per-run timeline from
the raw JSON: [`e6-restore-before-table.txt`](e6-restore-before-table.txt)
(`python -m fabric.experiments.e6_restore_report --label before`). Times are seconds after the restore command. "ND" = the leaf's
neighbor entry for spine1's link-local address resolved (`169.254.0.1 dev
eth1 lladdr …`, FRR's RFC 5549 entry). "Group" = the leaf kernel's ECMP
nexthop group for its BGP routes contains spine1's `eth1` nexthop again.

| | run 901 | run 902 | run 903 |
|---|---|---|---|
| spine1 links up | +0.20 | +0.20 | +0.18 |
| **leaf1–4: group re-includes spine1** (kernel, `ip monitor`) | **+0.20–0.21** | **+0.20–0.21** | **+0.18–0.19** |
| spine1 link-local addresses usable (DAD done) | +1.43–1.91 | +1.62–1.97 | +1.47–1.94 |
| leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4) | 1.99 / 1.99 / 1.99 / 1.99 | 2.89 / 1.89 / 1.89 / 1.89 | 2.60 / 1.60 / 2.60 / 2.60 |
| BFD up (leaf1 / 2 / 3 / 4) | 2.00 / 1.98 / 1.99 / 1.74 | 2.93 / 1.91 / 1.98 / 1.95 | 1.82 / 1.62 / 2.89 / 2.64 |
| BGP Established (leaf1 / 2 / 3 / 4) | **none (Active, ≈ 100 s)** / 2.08 / 1.99 / 2.04 | 2.93 / 1.91 / 1.98 / 1.95 | 2.62 / 1.62 / 2.89 / 2.64 |
| spine1 first / full prefixes received | 3.14 / 3.14 (10, leaf1 missing) | 3.13 / 4.13 (14) | 2.83 / 4.03 (14) |
| spine1 kernel FIB: first / last BGP route installed | 3.16 / 3.16 | 3.11 / 4.11 | 2.81 / 4.09 |
| leaf first BGP route via spine1 *from BGP* (leaf2–4; leaf1) | 3.36; none | 3.26; 4.21 | 2.91–4.19; 3.91 |
| **probe loss windows** (last reply → next reply) | rail B 1.95→3.21; ta1→ta3 1.98→2.28; tb1→tb4 1.77→2.29 | rail B 1.80→3.18; ta1→ta3 2.22→4.11 (3 gaps); tb1→tb4 2.48→4.16 (2 gaps) | rail B 2.59→4.17; tb1→tb4 2.04→2.90, 3.31→3.61 |
| probes with no loss after restore | rail A host1→host3, host3→host4, tb2→tb4 | same | same + ta1→ta3 |
| loss at the failure (any probe, gap > 0.25 s) | 0 | 0 | 0 |

**Verdict on the hypothesis as stated: no.** BGP doesn't put spine1 back
early. At link-up (+0.2 s), with the leaf↔spine1 session still Idle and BFD
down, the leaf's kernel ECMP group for its BGP routes already contains
spine1 again. The routes kept pointing at the same nexthop group (`nhid 31
= group 30/32` on leaf3) through the outage. The kernel dropped spine1's
member when the link went down, and zebra re-added it the moment the link
came up (`id 32 via fe80::… dev eth1 proto zebra` then `id 31 group 30/32`,
then 11 routes re-pointed at nhid 31, all at +0.20 s on leaf3). zebra keeps
an installed nexthop group for `zebra nexthop-group keep` seconds, default
180 ([FRR 10.2 zebra docs, Nexthop Tracking](https://docs.frrouting.org/en/stable-10.2/zebra.html)).

**The second half holds:** loss ends when spine1 has the route. In every
run each loss window closed within 0.1 s of spine1's kernel installing its
BGP routes (run 901: +3.16 → 3.21; run 902: +3.11 / 4.11 → 3.18 / 4.11 /
4.16; run 903: +4.09 → 4.17).

**What starts the loss:** the window opens within 0.1 s of the leaves
resolving spine1's link-local address (rail B: ND 1.99 / 1.89 / 2.60 →
last reply 1.95 / 1.80 / 2.59). From that moment a leaf can deliver packets
hashed onto `eth1` to spine1. spine1's only route for them is the mgmt
default (`default via 10.253.0.1 dev eth0`), because BGP hasn't yet given it
routes; it gets them ≈ 1.2–1.5 s after Established. `fib_multipath_use_neigh`
is 0 on the leaves, so the kernel doesn't steer around an unresolved
nexthop. Between +0.2 s and ND resolution, packets hashed onto spine1 should
also be lost (spine1's link-local addresses are still tentative). The probes
that lost packets show no gap there, and I didn't capture per-packet paths,
so **that part is unexplained**.

So the black hole is real and sits on the spine (no FIB yet). But the leaf
sends to spine1 because zebra reinstates the kernel nexthop group at
link-up, not because BGP chose spine1. Consequences for the fix:

- `bgp update-delay` doesn't apply. FRR 10.2 documents it for "BGP process
  restart or when a BGP process is cleared using 'clear ip bgp \*'"
  ([FRR 10.2 BGP docs](https://docs.frrouting.org/en/stable-10.2/bgp.html), `bgp update-delay MAX-DELAY [ESTABLISH-WAIT]`).
  In this drill bgpd never restarts.
- `bgp max-med on-startup` isn't in the 10.2 user guide's BGP page and, by
  name, also acts at process start. Neither knob changes the leaf's nexthop
  group, which BGP doesn't drive at that moment. **No intent knob was
  added** (step 2 skipped; step 3 instead).

Also seen: in run 901 the leaf1↔spine1 session stayed in Active/Connect
for the whole 44 s capture, and the post-run convergence check waited
**100.4 s** for it (runs 902 / 903: 2.5 / 2.6 s). That's the slow
re-establishment E6 predicted from F1's connect-retry and didn't see in the
first 21 runs. It caused no probe loss (leaf1's rail A probe had no gap),
because the other leaves didn't learn leaf1's prefixes via spine1.

### Next hypothesis

H2: the leaf re-adds spine1 to the kernel ECMP group at link-up because
zebra reinstalls the still-referenced nexthop group as soon as the
interface is up, independent of BGP. If H2 holds:

1. If zebra installed these routes without a shared kernel nexthop group
   (the exact FRR 10.2.1 setting still needs to be confirmed in the CLI; the
   10.2 user guide documents only `zebra nexthop-group keep`), the kernel group wouldn't regain spine1 until BGP re-learns the routes
   (+2.9–4.2 s above). eBGP ordering then guarantees spine1 has the prefix
   first, and the restore loss should drop to ≈ 0.
2. Or `net.ipv4.fib_multipath_use_neigh=1` on the leaves would not help
   once ND resolves (at +1.6–2.9 s), so it shouldn't close the window. That
   makes it a useful negative control.

Test H2 with the same drill and the same timeline before adding any intent
knob.

**Issue #32 status: still open.** Hypothesis "BGP selects the restored
spine before it has the table" is refuted. Measured mechanism: zebra
reinstates spine1 in the leaf's kernel ECMP group at link-up; the loss
starts when the leaf resolves spine1's link-local address and ends when
spine1's FIB has the route. No fix tested yet.
