# Leaf–spine link down, silent loss, or BFD flap

**Label: MEASURED-IN-LAB (EMULATED, shaped 500 Mbit/s)**: evidence in
[E6](../experiments/E6-failure-drills.md) (rows link down, silent loss, flap;
raw [`e6-results.json`](../experiments/e6-results.json)) and
[E2](../experiments/E2-bfd-convergence.md). Timings are Linux/FRR on veth,
not ASIC failover times.

## Symptom

- Collective step time up ~40% (E6: +7.1 to +9.1 s on a 20 s step) while one
  leaf↔spine link is out, recovering after it returns.
- A flapping link (down/up every 2 s) costs more than a single clean outage:
  E6 flap runs never reached the step target in 30 s (89–93% of it).
- Short loss bursts on probes through the link; *other rails unaffected*.

## Signals

| Signal | Command / query | What E6 showed |
|---|---|---|
| BFD peer state | `vtysh -c 'show bfd peers brief'`; dashboard "BFD peer up" (`fabric_bfd_peer_up`) | silent loss: BFD down → FIB change 0.54–0.57 s after the fault |
| BGP session | `vtysh -c 'show bgp summary'` (Up/Down column resets); `fabric_bgp_neighbor_established` | all 16 sessions back within 2.7–4.6 s of each run's end |
| Carrier | `ip -br link` on both ends (`NO-CARRIER`, `DOWN`) | carrier loss: first FIB change 0.25–0.26 s later |
| FIB churn | `ip -ts monitor route nexthop` on the leaf | the nexthop removed at inject, re-added 2.4–5.1 s after restore |
| Uplink rates | dashboard "Leaf uplink TX bytes/s" | the failed uplink at 0; sibling at the shaped limit; all ring pairs ≈ 230–270 Mbit/s (half rate) |
| Probe loss | `ping -D -i 0.1` through the link | carrier down: 1 lost (0.1 s); silent loss: 6–10 lost (0.5–0.7 s); **after restore**: tenant-b lost 8–16 (0.6–1.2 s) |

## Isolate

1. Identify the link: BFD/BGP peer down on the leaf (`eth1` = spine1 here) and
   the matching spine port. If BGP flaps while carrier stays up, suspect
   one-way loss (silent): check `tc -s qdisc`, errors and drops on both ends.
2. Count the flaps: `show bgp neighbors <if>` shows `Connections
   established/dropped` and the last reset reason. Several resets in seconds
   means a flapping optic or cable.
3. Check that only that link's flows are hit: same-leaf traffic and the other
   rail should be clean (E6: rail B and host3→host4 lost nothing).

## Remediate

- **Hard down:** nothing to do for routing; ECMP already removed it (< 0.3 s).
  Repair the link.
- **Silent loss:** BFD catches total loss (E6: 0.5–0.7 s). Shut the port so it
  stays out until repaired.
- **Flapping:** shut it administratively. Every up/down costs a reconvergence
  plus a restore transient (below). Return it only after the physical fix.
- **Return to service carefully.** E6's worst loss came *after* restore:
  ECMP re-added the path 2.4–5.1 s after link-up, and some flows lost up to
  1.2 s around that moment. Bring links back off-peak, one at a time.

## Verify

- `make fabric-test` (BGP 16/16, BFD up on every fabric link, 2 ECMP paths to
  each remote loopback, host and tenant reachability). E6 ran it after each fault type.
- Dashboard: both uplinks of the leaf carrying traffic again; step time back to baseline.

## Prevent

- Keep BFD on every fabric link (intent `bfd`: 100 ms × 3). E2 measured
  ≈ 1.0–1.1 s silent-loss recovery with BFD vs 7.9–9.7 s on the BGP hold timer.
- Dampen flaps: hold a link down after N flaps (e.g. link-flap error-disable on
  switches). The lab has none; E6 shows the cost.
- Test restore, not only failure (E6). Candidate mitigations to measure next:
  `bgp update-delay`/`max-med on-startup` on spines, delaying ECMP re-entry.
