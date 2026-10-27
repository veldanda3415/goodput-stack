# Spine or leaf loss: blast radius

**Label: MEASURED-IN-LAB (EMULATED, shaped 500 Mbit/s)**: evidence in
[E6](../experiments/E6-failure-drills.md) (rows spine loss and leaf loss).
"Loss" in the lab = every data port of that router taken down; the
container kept running.

## Symptom and blast radius (measured)

| Failure | Who is hit | Who is not | Step time / service |
|---|---|---|---|
| **Spine** (spine1) | every cross-leaf flow through spine1 on **both rails and both tenants**: 37–43 of 64 ring streams stalled ≥ 1 s; all six cross-spine probes lost 1.0–2.7 s | same-leaf traffic (rail A host3→host4: 0 lost) | fabric capacity halves; ring step +8.9 s or more (2 of 3 repeats did not finish in 30 s) |
| **Leaf** (leaf1) | host1 + host2 **rail A**, vmhost1 (its only NIC), tenant endpoints ta1 and tb1: every leaf1-attached probe lost 13.0–13.4 s (10 s fault + ≈ 3.3 s recovery); all 64 ring streams stalled 19–19.5 s | **rail B of the same hosts** (host1→host3 via leaf3/leaf4: 0 lost), tb2→tb4, same-leaf2 traffic | the ring collective stalls completely (≈ 10 Mbit/s per pair): two of its four members are cut off, and a collective runs at the pace of its slowest member |

**Collective job vs inference service.** A leaf failure is a *rail* failure
for every host behind it. A synchronous collective stops until that rail
returns or the job is restarted around it. Request-level services (inference
behind a load balancer) lose the endpoints on that leaf but keep serving from
the others, and the front-end tenants on other leaves saw nothing (tb2→tb4: 0 lost).

## Signals

| Signal | Command / query |
|---|---|
| Many BGP/BFD peers down on one router (spine) or on everything facing one leaf | `vtysh -c 'show bgp summary'` on all spines/leaves; `fabric_bgp_neighbor_established == 0` grouped by node; `fabric_bfd_peer_up` |
| Uplink rates | spine loss: every leaf's other uplink at the shaped limit, the spine's ports at 0; leaf loss: that leaf's uplinks at 0 |
| Host/rail view | host rail A unreachable while rail B answers (`ping -I <railA src>` vs `-I <railB src>`) |
| Tenant view | tenant endpoints on that leaf unreachable; type-2/type-5 routes from that VTEP withdrawn (`show bgp l2vpn evpn route`, next hop = that leaf loopback) |

## Isolate

1. Router-wide or link-local? All of a router's sessions down at once means
   node or port-group loss. One session means a link
   ([`link-down-bfd-flap.md`](link-down-bfd-flap.md)).
2. Map the blast radius from intent: which hosts and rails attach to the leaf
   (`hosts[].nics[].leaf`), which tenants have segments there
   (`tenants.vrfs[].segments`). That list is what to tell the job and service owners.

## Remediate

- **Spine:** no action needed for routing (remaining spines carry everything at
  reduced capacity). Repair, then return it carefully: E6's spine-loss loss
  windows (1.0–2.7 s) all came ≈ 4 s **after** the links came back.
  Instrumented rerun ([E6 restore transient](../experiments/E6-failure-drills.md#restore-transient)):
  leaves put the spine back in their kernel ECMP group at link-up, before
  BGP is up. The loss runs from the leaf resolving the spine's link-local
  address until the spine's FIB has the route (1.3–1.6 s on rail B).
  **Insertion procedure (measured, [E8 §3](../experiments/E8-restore-and-flap-fixes.md#3-spine-insertion-fix)):**
  1. Before the spine returns, set `no zebra nexthop kernel enable` on the
     leaves (`vtysh -c 'configure terminal' -c 'no zebra nexthop kernel
     enable'`, or render it with intent `zebra.leaf_kernel_nexthop_groups:
     false`). It applies to route installs made after the change, and the
     failure itself reinstalled the affected routes in E8.
  2. Restore the spine's links. Check that the leaves don't use it before BGP
     does: `ip route show <remote prefix>` on a leaf shows only the other
     spine until its session to the returning spine is Established and
     routes arrive (E8: +2.9–3.8 s).
  3. Check every session to that spine is Established within ≈ 5 s. A
     session stuck in `Active` waits FRR's 120 s ConnectRetry (`show bgp
     neighbors json` → `connectRetryTimer`); seen in 4 of 15 spine
     restores (#32 + E8) and 1 of 12 E8 flap runs.
  E8 result: rail-B restore loss 1.26 / 1.38 / 2.31 s → 0 / 0 / 0, no loss
  at the failure. Turning DAD off on the spine makes it worse (loss starts
  ≈ 1.2 s sooner; E8 §5), and lowering the spine's `coalesce-time` doesn't
  move the loss end (E8 §6).
- **Leaf:** the rail is gone for those hosts. For collectives, fail fast and
  reschedule onto healthy rails/pods rather than waiting (E6: stall for the
  whole outage plus ≈ 3.3 s). For services, drain the endpoints behind that
  leaf from the load balancer.

## Verify

`make fabric-test`: 16 BGP sessions, BFD, ECMP, rail reachability, VM
reachability, tenant reachability and isolation. E6 waited until all
sessions and BFD peers were up (2.7–4.6 s) before the next run, then ran the
suite after each fault type.

## Prevent

- Size for N−1 spines (E6: one of two spines = half the fabric).
- Keep hosts dual-railed to different leaves (the lab's rail A / rail B design
  is why host1 kept rail B through leaf1's loss).
- Scheduler awareness: map jobs to rails/pods so one leaf failure takes out as
  few jobs as possible. Test restore behavior, not just failure.
- Restore transient: **prevented in the lab** by `no zebra nexthop kernel
  enable` on the leaves (E8 §3, EMULATED, n = 3). `bgp update-delay` doesn't
  apply: it acts only on bgpd restart or `clear ip bgp *`. The setting is
  undocumented in the FRR 10.2 user guide, so test it on the target NOS and
  release before relying on it.
- Leaf loss doesn't touch jobs with no member behind that leaf: in E8 §7 a
  rail-B ring on the same four hosts kept 19.64–20.04 s steps (alone
  19.85–20.25 s) while leaf1 was down and the rail-A ring stalled.
