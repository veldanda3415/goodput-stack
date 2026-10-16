# ECMP imbalance / hash polarization

**Label: MEASURED-IN-LAB (EMULATED, Linux kernel ECMP)**: evidence in
[E5](../experiments/E5-collective-entropy.md), both the unshaped matrix and the
[shaped rerun](../experiments/E5-collective-entropy.md#shaped-uplinks-rerun).
Linux `fib_multipath_hash_policy` stands in for switch ASIC hashing; real
switches add seeds, symmetric options, and per-chip hash fields.

## Symptom

- Collective step time scales with the **busiest** uplink, not the average.
  In the shaped E5 rerun, measured job time tracked the busiest link's
  bytes ÷ rate (Pearson r = 0.998, within +0.27 s in all 36 cells).
- Ring collectives take about 2× as long as a measured even split
  (L3 hash: 6.03–6.17 s vs 3.09–3.30 s pinned).
- One uplink per leaf near 100% while its sibling idles, with no errors.

## Signals

| Signal | Command / query | Healthy | Imbalanced (measured) |
|---|---|---|---|
| Per-leaf max/mean uplink bytes | Dashboard "Leaf uplink max/mean imbalance": `max by (node)(rate(fabric_interface_tx_bytes_total{node=~"leaf[1-4]"}[1m])) / avg by (node)(…)` | ≈ 1.0–1.03 (L4, 16 flows/pair) | 1.995–2.0 (ring L3, or L4 with 1 flow/pair); ≈ 1.5 (all-to-all L3) |
| Uplink share of leaf TX | Dashboard "Uplink share of leaf TX" | ≈ 0.5 each | ≈ 1.0 / 0.0 |
| Raw counters | `ip -j -s link show` on a leaf (TX bytes delta per uplink) | similar deltas | one delta ≈ 2× the mean |
| Hash policy | `sysctl net.ipv4.fib_multipath_hash_policy` on leaves | 1 (L4) for many-flow jobs | 0 (L3): every flow of an IP pair takes one path |
| Flow entropy | flows per host pair in the job (NCCL channels/QPs) | ≥ 16 per pair (E5: L4/16 within +0.02–0.03 s of pinned) | 1 per pair: L4 can't help (ring L4/1 collided in 3/3 repeats) |

## Isolate

1. Confirm it's imbalance, not loss: drops and retransmits on the busy link
   look like normal congestion (TBF drops in the lab), and BGP/BFD are stable.
2. Check the hash policy and the job's flow count per pair. L3 hashing with
   one IP pair per direction **cannot** spread, whatever the flow count
   (E5 shaped: ring L3 with 16 flows was still 1.995).
3. Look for polarization: if every tier uses the same hash inputs and seed,
   a leaf and spine pick correlated paths (not reproducible in a 2-tier,
   2-spine lab; documented as a production risk).

## Remediate

- Switch to an L4 (5-tuple) hash on leaves: `fib_multipath_hash_policy=1` in
  the lab; on switches, include UDP source port for RoCE (QP entropy).
- Raise flow entropy: more QPs or channels per GPU pair (Llama 3's 16 flows
  per pair, S13 in [`../design/sources.md`](../design/sources.md)).
- For persistent hot pairs: per-flow pinning or adaptive routing / packet
  spraying (switch-dependent). The lab's pinned profile
  (`make fabric-shape-on`, `python -m fabric.tools.shaping pin ring`) is a
  *measurement baseline*, not a production fix.

## Verify

- Max/mean imbalance ≤ ~1.05 per leaf over the job window. Step time within
  a few % of the even-split baseline (E5 shaped: gap +0.02 s at 16 flows/pair).

## Prevent

- Hash policy and fields rendered from intent, the same on every switch.
- Alert on the per-leaf max/mean ratio staying > 1.3 for minutes during jobs.
- Capacity planning on max-link load, not mean.
