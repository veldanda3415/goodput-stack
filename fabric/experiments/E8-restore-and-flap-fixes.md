# E8 — Restore and flap fixes

**Label: EMULATED, SHAPED.** Same lab as [E6](E6-failure-drills.md):
containerlab 0.78.2, rootful Podman 5.7.0, FRR 10.2.1, veth + Linux
forwarding, leaf↔spine links TBF-shaped to 500 Mbit/s per direction. Scripts
that stand in for a NOS feature are labelled **EMULATED-POLICY**. All timings
are Linux/FRR software timings on one WSL2 VM, not switch ASIC times.

E8 turns three hypotheses from E6 and its [restore transient](E6-failure-drills.md#restore-transient)
section (#32) into measurements:

- (A) which timers set the length of the restore loss window;
- (B) a fix that keeps a restored spine out of the leaves' ECMP until it has
  routes (#32 H2);
- (C) a link-flap hold-down that cuts the > +30 s flap cost.

Starting facts (measured in E6 / #32, not re-derived here): after the
spine-loss restore, the leaves' kernel ECMP group re-includes spine1 at
+0.18–0.21 s while BGP is still Idle; spine1's link-local addresses finish DAD
at +1.43–1.97 s; rail-B loss opens within 0.1 s of the leaves resolving spine1
(ND, +1.89–2.60 s) and closes within 0.1 s of spine1 installing its BGP routes
(+3.16–4.11 s). No loss at the failure.

Runner: `python -m fabric.experiments.e8 …` ([`e8.py`](e8.py)). It reuses the
E6 drill runner ([`e6_drills.py`](e6_drills.py): `run_once`, `fault_flap`,
`converged`), the #32 instrumentation ([`e6_restore.py`](e6_restore.py):
`run`, the 10 Hz poller and `ip -ts monitor` on one host clock, container UTC
stamps parsed as UTC) and the #32 timeline report
([`e6_restore_report.py`](e6_restore_report.py)). Raw command output is in
[`e8/raw/`](e8/raw/).

## 0. Preflight

2026-10-27 11:25–11:29 EDT, branch `ravi/fault_measurement` from `main`
(9116bdd). `make fabric-up && make fabric-shape-on`, then `make fabric-test`:
**69 passed**. Raw: [`e8/raw/t0-preflight.txt`](e8/raw/t0-preflight.txt).

| Item | Value |
|---|---|
| containerlab / Podman | 0.78.2 / 5.7.0 (rootful via setuid containerlab) |
| FRR | 10.2.1_git (spine1, leaf1, leaf3) |
| Kernel | 6.18.33.2-microsoft-standard-WSL2 (shared by all containers) |
| iproute2 in routers / hosts | 6.9.0 / 6.15.0; iperf 3.18 |
| Host | `nproc` 16; load average 1.41 / 1.65 / 1.15 before, 1.02 / 1.54 / 1.13 after the idle sample |
| `vmstat 5` idle, 7 samples | us 2–4 %, sy 2–4 %, id 91–96 %, wa 0, r 0–2 |

Reused commands:

- restore drill: `e6_restore.run(intent, run_no)` (spine1 eth1–eth4 down at
  T0+10 s, up at T0+20 s, ring load, six ping probes at 0.1 s, pollers and
  monitors on spine1 + leaf1–4), wrapped by `e8 restore --label L [--knob K]`;
- timeline: `e6_restore_report.report(run)` → the same columns as Build 10;
- flap: `e6_drills.run_once(intent, "flap", fault_flap(), run_no, duration)`
  with a longer `duration`, wrapped by `e8 flap`; step time from
  `e6_report.step_time` with E6's W = 1.204 GB;
- shaping: `make fabric-shape-on`; checks: `make fabric-test`.

## 1. Timer and DAD audit (no traffic)

`python -m fabric.experiments.e8 audit` → [`e8/raw/t1-audit.txt`](e8/raw/t1-audit.txt)
(spine1, leaf1 rail A, leaf3 rail B; all sessions Established, no traffic).
Which commands this FRR build parses: `strings` of the running `zebra` and
`bgpd` binaries → [`e8/raw/t1-cli-strings.txt`](e8/raw/t1-cli-strings.txt).
vtysh's `find` and `list` here only search vtysh's own command tree, and `?`
needs a tty, so the binaries' command definitions are the CLI check.

### What is configured

- `frr defaults traditional` on every router. FRR's docs name the profiles
  but do not list what they change ([FRR 10.2 basic, Profiles](https://docs.frrouting.org/en/stable-10.2/basic.html)).
  The values below are read from the running routers.
- Per neighbor (all 8 sessions audited): `timers 3 9` (keepalive 3 s, hold
  9 s), `connectRetryTimer` **120 s**, `minBtwnAdvertisementRunsTimerMsecs`
  **0** (MRAI 0), no `update-delay`, no `timers connect`, no
  `advertisement-interval`, no `coalesce-time` in the running config.
- `show bgp ipv4 unicast update-groups`: MRAI 0 s everywhere. **Coalesce Time
  1250 ms** on spine1's four subgroups and **1150 ms** on leaf1's and leaf3's.
  The documented default is 1000 ms ([FRR 10.2 BGP, `coalesce-time`](https://docs.frrouting.org/en/stable-10.2/bgp.html)).
  The extra 150–250 ms is FRR's own adjustment, not configured here; I have
  not found it documented.
- zebra: `show zebra` reports **Kernel NHG Available** and "v4/v6 All
  LinkDown Routes Off". The running config has no `zebra nexthop …` lines, so
  the defaults apply. The binary defines `[no] zebra nexthop kernel enable`,
  `[no] zebra nexthop proto only`, `[no] zebra nexthop-group keep (1-3600)` and
  `[no] zebra nexthop resolve-via-backup`. Only `zebra nexthop-group keep` is
  in the 10.2 user guide: "the time that zebra will keep a created and
  installed nexthop group before removing it from the system if the nexthop
  group is no longer being used. The default time is 180 seconds"
  ([FRR 10.2 zebra, Nexthop Tracking](https://docs.frrouting.org/en/stable-10.2/zebra.html)).
  The other two are undocumented in the 10.2 guide.
- bgpd also defines `bgp max-med administrative`, `bgp max-med on-startup`,
  `bgp suppress-fib-pending` ("wait for fib installation before announcing
  routes", FRR 10.2 BGP docs) and `coalesce-time (0-4294967295)`.
- Leaves with spine1 up: remote prefixes share one kernel nexthop group, e.g.
  leaf3 `10.210.1.8/30 nhid 36` = `group 28/31`, where `id 31 via
  fe80::…:accb dev eth1` is spine1 and `id 28 … dev eth2` is spine2. leaf1
  is the same with `nhid 47 = group 38/41`. All objects are `proto zebra`.
- Kernel IPv6 on spine1 eth1–eth4: `accept_dad=1`, `dad_transmits=1`,
  `router_solicitation_delay=1`, `optimistic_dad=0`, `use_optimistic=0`,
  `neigh.retrans_time_ms=1000`. Leaves' eth1/eth2: `accept_dad=1`,
  `dad_transmits=1`. `net.ipv4.fib_multipath_use_neigh=0` on every router.

### Role in bring-up

| Timer / knob | Value | Restore gap it can affect | Why | Source |
|---|---|---|---|---|
| DAD: `accept_dad`, `dad_transmits`, ND `retrans_time_ms` | 1, 1, 1000 ms | **loss start** (and BGP start) | A new link-local address stays tentative for `dad_transmits × RetransTimer` = 1 s. RFC 4862 §5.4.2 also delays the first NS by a random 0–`MAX_RTR_SOLICITATION_DELAY` (1 s) when an interface is initialized. That matches the measured +1.43–1.97 s. Until DAD finishes, spine1 can't answer ND for its link-local address and can't open BGP TCP from it. | ip-sysctl.rst (`accept_dad` 1 = "Enable DAD (default)", `dad_transmits` default 1); RFC 4862 §5.1, §5.4 |
| `optimistic_dad` / `use_optimistic` | 0 / 0 | loss start | With optimistic DAD (RFC 4429) the address is usable before DAD finishes. | ip-sysctl.rst |
| Leaf ND retransmit (`retrans_time_ms`) | 1000 ms | **loss start** | A leaf whose first NS for spine1 got no answer retries 1 s later. The measured ND times sit on a 1 s grid (run 902: 2.89 vs 1.89; run 903: 2.60 vs 1.60). | ip-sysctl.rst / RFC 4861 RetransTimer |
| `router_solicitation_delay` | 1 s | neither | Applies only to Router Solicitations; nothing here uses RA. | ip-sysctl.rst |
| zebra kernel nexthop objects (`zebra nexthop kernel enable`, default) | on (`Kernel NHG Available`) | **loss start** (H2 candidate) | Routes point at a shared kernel group object. If zebra re-adds spine1's member when the link comes up, every route using the group gets spine1 back at once. | `show zebra`; bgpd/zebra binary |
| `zebra nexthop-group keep` | 180 s (default) | loss start (H2 candidate) | Keeps an unused group installed for 180 s. A 10 s outage is inside that window, so the old group is still there at restore. | FRR 10.2 zebra docs |
| `zebra nexthop proto only` | off (default) | neither expected | Undocumented in the 10.2 guide; by name, restricts which kernel nexthop objects zebra uses. | binary |
| `fib_multipath_use_neigh` | 0 | loss start (partly) | With 1, the kernel skips a multipath member whose neighbor is FAILED. It can't help once ND has resolved, which is exactly when loss starts. | ip-sysctl.rst |
| BGP keepalive / hold | 3 / 9 s | neither | Failure detection. On bring-up, OPEN and KEEPALIVE are sent immediately. | `show bgp neighbors json` |
| BFD | 100 ms × 3 | neither | Failure detection. BFD up and BGP Established land within 0.1 s of each other in #32. | rendered `frr.conf` |
| ConnectRetry | **120 s** | **loss end** (when the first connect attempt fails) | If the first TCP attempt fails while both sides sit in Active, the next attempt waits up to 120 s. Spine1 then lacks that leaf's prefixes for ≈ 2 min. | `connectRetryTimer` in `show bgp neighbors json` |
| Update-group coalesce | 1150 ms (leaves), 1250 ms (spine1) | **loss end** (the leaves' value) | After Established, an advertiser waits about the coalesce time before building its first UPDATE. Loss ends when spine1 has the leaves' prefixes, so the **leaves'** coalesce sets it. Measured #32: Established → spine1 first prefixes ≈ 1.1–1.5 s. Spine1's own coalesce delays only spine1 → leaf updates, which the leaves don't need to start forwarding (H2). | `show bgp ipv4 unicast update-groups`; FRR 10.2 BGP docs |
| MRAI (`advertisement-interval`) | 0 s | neither (it is 0) | No delay between update runs. | `show bgp neighbors json`, update-groups |
| `bgp update-delay` | not set (off) | neither | Only on bgpd restart or `clear ip bgp *` (FRR 10.2 BGP docs); bgpd keeps running in this drill (#32). | running config; docs |
| `bgp suppress-fib-pending` | not set | neither for this gap | Delays a router's *advertisements* until its own FIB has the route. The leaves' forwarding to spine1 doesn't depend on spine1's advertisements (H2). | FRR 10.2 BGP docs |

Consequence for Task 6: the plan says to lower **spine1's** coalesce. By the
row above, that should *not* move the loss end, because the end is set by
the leaves → spine1 UPDATE. Task 6 records both predictions and tests the
knob as planned (§6).

### The 100 s stall (#32 run 901)

**Verdict: yes, consistent with the 120 s ConnectRetry timer** (within the
≈ 4 s resolution of the wait loop).

From the retained `e6-restore-results.json` poller samples (seconds after the
restore command): spine1 eth1 Idle → **Connect +1.44** → **Active +2.04**;
leaf1 eth1 Idle → **Active +2.0**. Neither side reached Established in the
44 s capture. The post-run snapshot has `peerUptimeMsec` 34 000 (spine1) and
33 000 (leaf1) for sessions that went down at −9.77 / −9.71 s. So the snapshot,
and the start of `converged()`, is at ≈ +24 s. `converged()` waited 100.4 s,
so Established ≈ +124–125 s. Active (+2.0) → Established ≈ 122 s, against
`connectRetryTimer` 120 s.

The 2 s difference is inside the resolution of `converged()`: each pass
makes 12 `containerlab exec` calls before sleeping 1 s. The likely cause of
the failed first attempt: spine1 tried to connect at +1.44 s, the earliest
moment its link-local address could be out of DAD (+1.43 s). The timing is
consistent with that, but it wasn't captured (no tcpdump), so it stays
unproven.

Also seen, not chased: `peerBfdInfo` in `show bgp neighbors json` reports
rx/tx 300 ms, while the BFD profile sets 100 ms. Not investigated here; E2
measured the BFD session's detection time directly.

## 2. Same-day baseline restore

`python -m fabric.experiments.e8 restore --label baseline` = the #32 drill
(`e6_restore.run`) ×3, shaped, L4 hash, ring load. Results:
[`e8-restore-results.json`](e8-restore-results.json); table:
`python -m fabric.experiments.e8 restore-report --label baseline`. The table
code reproduces the Build 10 table from `e6-restore-results.json` exactly
(checked before these runs).

**Prediction (written before the runs):** same sequence as Build 10, within
its spread. Group re-includes spine1 at ≈ +0.2 s; DAD done +1.4–2.0 s; ND
+1.6–2.9 s on a 1 s grid; Established +1.6–2.9 s; spine1 FIB first / last
+2.8–3.2 / +3.2–4.1 s; rail-B loss opens at ND and closes at spine1's FIB
install (≈ 1.2–1.6 s long); no loss at the failure. A run-901-style stall
(one session in Active for 120 s) is possible in about 1 of 3 runs.

### Results (2026-10-27, 11:36–11:39 EDT, runs 801–803)

Seconds after the restore command. Table file: [`e8/raw/t2-baseline-table.md`](e8/raw/t2-baseline-table.md).

| | run 801 | run 802 | run 803 |
|---|---|---|---|
| spine1 links up | +0.18 | +0.19 | +0.20 |
| leaf1–4: group re-includes spine1 | 0.18 / 0.18 / 0.18 / 0.18 | 0.19 / 0.20 / 0.20 / 0.20 | 0.20 / 0.21 / 0.21 / 0.21 |
| spine1 link-local DAD done (first / last) | 1.38 / 2.12 | 1.24 / 1.86 | 1.28 / 1.82 |
| leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4) | 1.67 / 2.67 / 2.67 / 2.67 | 2.72 / 1.72 / 1.72 / 1.72 | 2.42 / 2.42 / 1.42 / 2.42 |
| BFD up (leaf1 / 2 / 3 / 4) | 1.84 / 2.73 / 2.67 / 2.73 | 2.01 / 1.71 / 1.77 / 1.74 | 1.93 / 1.95 / 1.88 / 2.46 |
| BGP Established (leaf1 / 2 / 3 / 4) | 1.84 / 2.73 / 2.67 / 2.73 | 2.81 / 1.71 / 1.77 / 1.74 | 2.43 / 2.45 / 1.88 / 2.46 |
| spine1 first / full prefixes received | 3.06 / 3.86 | 2.89 / 3.89 | 3.02 / 3.62 |
| spine1 kernel FIB: first / last BGP route | 3.06 / 3.88 | 2.94 / 3.93 | 3.07 / 3.63 |
| leaf first BGP route via spine1 in FIB (leaf1 / 2 / 3 / 4) | 3.16 / 4.09 / 4.09 / 4.09 | 4.03 / 3.04 / 3.04 / 3.04 | 3.83 / 3.83 / 3.17 / 3.83 |
| probe loss after restore (last reply → next reply) | railA host1->host3 1.62→3.94; railB host1->host3 2.66→3.92; tenant-a ta1->ta3 1.88→2.40, 2.60→3.97 | railA host1->host3 2.00→4.01; railB host1->host3 1.65→3.03; tenant-a ta1->ta3 2.00→2.43, 2.93→3.98; tenant-b tb2->tb4 2.40→2.82 | railA host1->host3 1.92→3.70; railB host1->host3 1.34→3.65; tenant-a ta1->ta3 1.54→2.37, 2.37→3.73 |
| loss at the failure (s after inject) | none | none | none |
| wait to all-up after the run, s | 2.7 | 2.5 | 2.6 |

**Matches Build 10: yes, within run-to-run spread.**

- Group re-includes spine1 at +0.18–0.21 s on all four leaves (Build 10:
  +0.18–0.21).
- DAD done +1.24–2.12 s (Build 10: +1.43–1.97). The earliest finish is
  0.2 s earlier than before; RFC 4862's random 0–1 s initial delay covers
  that.
- ND sits on a 1 s grid again (1.67 / 2.67, 1.72 / 2.72, 1.42 / 2.42).
- Established +1.71–2.81 s; spine1 FIB first / last +2.94–3.07 / +3.63–3.93 s
  (Build 10: +2.81–3.16 / +3.16–4.11).
- **Rail-B loss window: 1.26 / 1.38 / 2.31 s** (2.66→3.92, 1.65→3.03,
  1.34→3.65; Build 10: 1.26 / 1.38 / 1.58). It opens within 0.1 s of leaf3's
  ND for spine1 (2.67 / 1.72 / 1.42) and closes within 0.1 s of a spine1 FIB
  install (3.88 / 2.94 / 3.63).
- No loss at the failure; no ConnectRetry stall (all-up wait 2.5–2.7 s).

Difference from Build 10: today the rail-A probe host1→host3 (leaf1→leaf2)
also lost 1.8–2.3 s in every run (Build 10: none). A single ping flow
always hashes to one uplink. The leaves run `fib_multipath_hash_seed=0`,
which means "an internal random-generated" seed (ip-sysctl.rst), and every
`fabric-up` creates new network namespaces, so a probe sees the black hole only if its hash lands on
spine1. That is a probe-coverage limit, not a change in behaviour. A ping
gap covers both directions, so a window can open at either leaf's ND (run
802: leaf2's at 1.72 s, before leaf1's at 2.72 s).

## 3. Spine insertion fix

### 3a. Mechanism (H2)

H2 (#32): the leaf re-adds spine1 to the kernel ECMP group at link-up
because zebra reinstalls the still-referenced nexthop group as soon as the
interface is up, independent of BGP.

Method: `python -m fabric.experiments.e8 mechanism` (no traffic). On
leaf3 (rail B): enable `debug zebra events / nexthop detail / rib / kernel`
into `log file /tmp/frr-e8.log`, put spine1 eth1–eth4 down, and after 5 s
snapshot leaf3's kernel nexthops and routes, `show nexthop-group rib`,
`show ip route 10.210.1.8/30` and `show bgp ipv4 unicast 10.210.1.8/30`. Then
run `ip -ts monitor nexthop route link` and `ip -6 -ts monitor neigh` on leaf3
and bring spine1's links up. The debug lines and log file are removed
afterwards.

**Prediction (written before the run):**

1. With spine1 down, BGP on leaf3 has only spine2's path for remote
   prefixes, and the kernel route points at a single nexthop (spine2). But
   zebra's NHG for the two-path group (kernel `id 36 group 28/31` before) is
   still in `show nexthop-group rib` with the spine1 member inactive, kept by
   `nexthop-group keep` (180 s) or still referenced.
2. At link-up, before any BGP event, zebra (`proto zebra`) re-adds the
   singleton nexthop for spine1's link-local on eth1 and then the group
   containing it, and moves routes onto that group. The zebra debug log shows
   the trigger as an interface-up event, not a route update from bgpd.

H2 is **refuted** if the routes stay on the spine2-only nexthop until bgpd
sends an update, or if the kernel itself (no `proto zebra` object) restores
the member.

**Result (2026-10-27 11:40:51–11:41:12 EDT, leaf3):** raw
[`e8/raw/t3a-mechanism.txt`](e8/raw/t3a-mechanism.txt) (snapshots, both
monitors, the full zebra debug log). **Verdict on H2: yes.** The mechanism
has two steps, both in zebra, and only the second was in H2:

1. **At link-down, zebra keeps the old group.** bgpd withdraws spine1's
   path and sends the route with spine2 only. zebra compares it with the
   installed entry, ignores the now-inactive spine1 member, and keeps the old
   two-member nexthop entry:

   ```
   15:40:51 zebra_nhg_rib_compare_old_nhe: 10.210.1.8/30 new id: 28 old id: 36
   15:40:51 zebra_nhg_nexthop_compare: 10.210.1.8/30 Old is not active going to the next one
   15:40:51 zebra_nhg_rib_compare_old_nhe:10.210.1.8/30 They are the same, using the old nhg entry
   15:40:51 netlink_route_multipath_msg_encode: 10.210.1.8/30 nhg_id is 36
   ```

   Five seconds into the outage, BGP has one path (`Paths: (1 available …)
   … from eth2`), but zebra's RIB entry still lists spine1
   (`fe80::…:accb, via eth1 inactive`). Zebra NHG 36 still `Depends: (28)
   (31)` with RefCnt 11 (all 11 remote routes). The kernel object `id 36` was
   pruned to `group 28`.
2. **At link-up, zebra reinstalls that group without asking BGP.** Kernel
   events and the zebra log, seconds after the restore command (11:40:58.893):

   ```
   +0.19 [kernel] eth1 … state UP
   +0.19 [zebra]  Intf eth1(1381) has come UP
   +0.19 [zebra]  zebra_interface_nhg_reinstall: Installing interface eth1 associated NHGs into kernel
   +0.19 [zebra]  zebra_interface_nhg_reinstall: Setting the valid flag for nhe 31[fe80::a8c1:abff:feae:accb if 1381 vrfid 0]
   +0.19 [zebra]  zebra_interface_nhg_reinstall dependent nhe 36[28/31] Setting Reinstall flag
   +0.19 [kernel] id 31 via fe80::a8c1:abff:feae:accb dev eth1 scope link proto zebra
   +0.19 [kernel] id 36 group 28/31 proto zebra
   +0.19 [kernel] 11 routes "nhid 36 proto bgp", now with both nexthops (eth2 + eth1)
   +1.46 [kernel] fe80::a8c1:abff:feae:accb dev eth1 FAILED      (spine1 LL still tentative)
   +2.37 [kernel] fe80::a8c1:abff:feae:accb dev eth1 … router DELAY   (ND resolved)
   +3.74 [kernel] 10.200.0.1 nhid 31 … proto bgp                (first BGP-driven change)
   ```

The FRR 10.2 source shows why: `if_up()` calls
`zebra_interface_nhg_reinstall(ifp)` **unconditionally**. Its comment
reads: "Interface associated NHG's have been deleted on interface down events,
now that this interface is coming back up, let's resync the zebra -> dplane
nhg's so that they can be continued to be used". The function's own header
names the use case "a quick port flap" where zebra believes nothing changed
([zebra/interface.c](https://github.com/FRRouting/frr/blob/stable/10.2/zebra/interface.c),
[zebra/zebra_nhg.c](https://github.com/FRRouting/frr/blob/stable/10.2/zebra/zebra_nhg.c)).
`zebra_nhg_rib_compare_old_nhe` is called from `nexthop_active_update`
under a changed route of the same type, and neither function checks any
zebra flag (`nhg keep`, `proto only`, kernel nexthops). So **no 10.2.1 knob
turns either step off directly**. The reinstall is a deliberate
fast-recovery feature. It is right for a flap where the far end keeps its
FIB, and wrong for a spine that comes back with an empty FIB.

Not settled here: the #32 "unexplained" part. Between +0.2 s and ND
resolution, packets hashed to spine1 wait on an unresolved neighbor. This run
had no traffic, so it doesn't say whether they are dropped.

### 3b. Candidate fixes

#### Candidate 1: `no zebra nexthop kernel enable` on the leaves

The knob exists in 10.2.1 (`[no] zebra nexthop kernel enable` in the zebra
binary, `Kernel NHG Available` in `show zebra`). It isn't in the 10.2 user
guide. With it off, zebra should install routes with inline nexthops
instead of shared kernel group objects.

**Prediction (written before the runs):** step 1 above (RIB reuse) still
happens, since it is RIB logic. But with no kernel group object, the link-up
reinstall (step 2) has no shared object to refresh. Whether the routes come
back with spine1 before BGP then depends on whether zebra re-processes the
routes at `if_up`. The source shows `if_up()` doesn't call `rib_update`, so I
predict **it works**: routes stay spine2-only until bgpd sends two paths
(+2.9–4.2 s), when spine1 already has the prefixes. Rail-B restore loss → 0,
no loss at the failure, bring-up (all sessions Established) unchanged.
Confidence about 60 %. Risk: the kernel itself revives a dead inline nexthop
at link-up (IPv4 multipath `RTNH_F_DEAD` handling). That would bring back
the same loss at +0.2 s.

First a no-traffic check that the knob takes effect at runtime (no FRR
restart allowed).

No-traffic check on leaf3 first ([`e8/raw/t3b-c1-probe.txt`](e8/raw/t3b-c1-probe.txt)):
the command is accepted and shows in `show running-config`, but installed
routes keep `nhid 36` until they are reinstalled. The knob applies per
install. A spine1 down/up cycle with the knob on leaf3
([`e8/raw/t3b-c1-mechanism.txt`](e8/raw/t3b-c1-mechanism.txt); an
earlier attempt crashed in my script before saving output and is not
counted):

- During the outage, routes are inline and spine2-only:
  `10.210.1.8/30 via 169.254.0.1 dev eth2 proto bgp metric 20 onlink`.
- At link-up (+0.14 s) there is **no route event**. The kernel does not
  revive anything.
- ND resolved at +2.48 s. The first route change is at **+3.98 s**, when all
  11 remote routes gain `nexthop via 169.254.0.1 dev eth1` from bgpd.

Then `python -m fabric.experiments.e8 restore --label c1-no-kernel-nhg --knob no-kernel-nhg`.
The knob goes on leaf1–4, followed by one no-traffic spine1 down 3 s / up
cycle so every route is reinstalled under it. Then 3 restores, then the
revert (`zebra nexthop kernel enable` + the same cycle). Runs 804–806,
2026-10-27 11:48–11:52 EDT. A column was added for both install styles:
"leaf kernel routes to remote prefixes use spine1" comes from the 10.2.1
poller's `ip -4 route show proto bgp` grouped by device. The monitor-based
"group" column only sees nexthop-group objects, and the monitor parser keeps
only each event's first line, so it shows "—" for inline routes. Baseline
for that column (runs 801–803): **+0.21–0.28 s**.

| | run 804 | run 805 | run 806 |
|---|---|---|---|
| spine1 links up | +0.16 | +0.27 | +0.23 |
| leaf1–4: group re-includes spine1 | — / — / — / — | — / — / — / — | — / — / — / — |
| spine1 link-local DAD done (first / last) | 1.38 / 1.83 | 1.33 / 2.16 | 1.28 / 2.08 |
| leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4) | 2.42 / 2.42 / 1.42 / 1.42 | 2.24 / 2.24 / 2.24 / 2.24 | 2.30 / 2.30 / 1.30 / 2.30 |
| BFD up (leaf1 / 2 / 3 / 4) | 1.92 / 1.88 / 1.61 / 1.43 | 1.94 / 2.26 / 1.95 / 2.32 | 2.16 / 2.32 / 1.38 / 2.07 |
| BGP Established (leaf1 / 2 / 3 / 4) | 2.42 / 2.48 / 1.61 / 1.43 | 2.24 / 2.26 / 2.25 / 2.32 | 2.36 / 2.32 / — / 2.37 |
| spine1 first / full prefixes received | 2.59 / 3.60 | 3.45 / 3.45 | 3.49 / — |
| spine1 kernel FIB: first / last BGP route | 2.64 / 3.64 | 3.46 / 3.46 | 3.51 / 3.51 |
| leaf first BGP route via spine1 in FIB (leaf1 / 2 / 3 / 4) | — / — / — / — | — / — / — / — | — / — / — / — |
| leaf kernel routes to remote prefixes use spine1 (poller, leaf1 / 2 / 3 / 4) | 3.82 / 3.78 / 3.01 / 2.93 | 3.64 / 3.57 / 3.55 / 3.62 | 3.77 / 3.72 / — / 3.77 |
| probe loss after restore (last reply → next reply) | none | none | none |
| loss at the failure (s after inject) | none | none | none |
| wait to all-up after the run, s | 2.5 | 3.5 | 105.5 |

Before / after, rail-B probe (host1→host3, leaf3→leaf4) and all probes:

| | Baseline 801 / 802 / 803 | Candidate 1 804 / 805 / 806 |
|---|---|---|
| leaves use spine1 for remote prefixes | +0.21–0.28 s | **+2.93–3.82 s** (after spine1's first FIB install, +2.64 / 3.46 / 3.51) |
| rail-B restore loss window | 1.26 / 1.38 / 2.31 s | **0 / 0 / 0** |
| any probe, restore loss | 3–4 probes per run, up to 2.3 s | **none** (6 probes × 3 runs) |
| loss at the failure | none | none |
| BGP Established (all 4) | +1.71–2.81 s | +1.43–2.48 s (806: leaf3 stalled, below) |
| wait to all-up after the run | 2.5–2.7 s | 2.5 / 3.5 / **105.5** s |

**Verdict on candidate 1: works.** Mechanism: zebra installs inline
multipath routes instead of shared kernel group objects, so the link-up
`zebra_interface_nhg_reinstall` has no shared object to refresh. The routes
stay on spine2 until bgpd sends the two-path route. eBGP ordering then means
spine1 already has the prefix. Spine1 carries traffic about 3.5 s later than
in the baseline. In the baseline those first ≈ 3.5 s were black-holed on
spine1 anyway, so no useful capacity is lost.

Run 806 hit the 120 s ConnectRetry stall again (leaf3↔spine1 Active; all-up
wait 105.5 s, as in #32 run 901). Seen 1 of 3 in Build 10, 0 of 3 in today's
baseline, 1 of 3 here, so I can't attribute it to the knob. It cost no
loss: with the knob, no leaf sends to spine1 without a BGP path, and the
other leaves never learned leaf3's prefixes via spine1. Under the default
config, H2's reinstall would still put spine1 into the other leaves' groups
for leaf3's prefixes at link-up. That is inferred from 3a, not measured with
a stalled session.

Rendered from intent: `zebra.leaf_kernel_nexthop_groups` (default `true`,
lab unchanged). `false` renders `no zebra nexthop kernel enable` on leaves
only. Test: `test_renderer_leaf_kernel_nexthop_groups_knob`. The default
render is byte-identical to before (`make fabric-render`, no diff in
`fabric/build/example`). The lab default is not flipped in this branch: the
rules ask for every knob to be reverted, and E1–E7 results were taken with
kernel nexthop groups.

Revert check: no `zebra nexthop` line on leaf1–4, remote routes back on
`nhid` objects, `make fabric-test` **69 passed**.

Candidates 2 and 3 were **not tried**: the plan stops at the first
candidate that removes the loss without adding failure loss or slowing
bring-up.

### 3c. Summary

| Candidate | Restore loss (rail B, per run) | At-failure loss | Bring-up (sessions) | Verdict |
|---|---|---|---|---|
| none (baseline 801–803) | 1.26 / 1.38 / 2.31 s | none | +1.71–2.81 s | — |
| 1: `no zebra nexthop kernel enable` on leaves (804–806) | 0 / 0 / 0 | none | +1.43–2.48 s (1 ConnectRetry stall, harmless) | **works** |
| 2: change at the layer 3a found | not tried | | | stopped at candidate 1 |
| 3: scripted insert procedure | not tried | | | stopped at candidate 1 |

Limits: n = 3 per condition; ping probes see only the uplink their hash
picks (6 flows); the inline-route install costs zebra more netlink work per
route change (11 routes here, not measured at scale); the knob is
undocumented in the 10.2 user guide.

## 4. Flap cost and hold-down

### 4a. Baseline flap, window extended until the step completes

`python -m fabric.experiments.e8 flap --label baseline-flap` = E6's
`fault_flap` exactly: spine1 `ip link set eth1 down; sleep 2; … up; sleep 2`
×5 from T0+5 s to T0+25 s, ring L4 16 flows/pair, shaped. The difference:
`iperf3 -t 60` instead of 30, so the step (slowest pair reaches E6's
W = 1.204 GB) completes inside the window. Added samplers:

- `nstat -asz TcpRetransSegs TcpExtTCPTimeouts TcpExtTCPLossProbes
  TcpExtTCPSpuriousRTOs TcpOutSegs` every 0.5 s on the four senders;
- `ss -tin` every 1 s on host1;
- leaf1 and leaf2 eth1/eth2 tx/rx byte counters at 10 Hz;
- at T0+≈4 s, every ring flow's 5-tuple (`ss -tnH` on host1–4) and its uplink
  from `ip route get <dst> from <src> iif <host port> ipproto tcp sport <s>
  dport <d>` on its source leaf. That gives the flows that move off spine1
  on each down and back on each up.

Per-flow throughput comes from iperf3's 0.5 s per-stream server intervals,
as in E6. Raw: [`e8-flap-results.json`](e8-flap-results.json).

**Prediction (written before the runs):**

- Full step time ≈ 32–36 s, i.e. +12–16 s over the 20.0 s baseline. E6 got
  89–93 % of W at 30 s. At the ≈ 230–270 Mbit/s fault-window pair rate (half
  rate), the remaining 7–11 % of 1.2 GB takes another ≈ 3–4 s, plus recovery.
- About half of each leaf's 32 outgoing flows hash to spine1, and those move
  on every down and every up: ≈ 16 per leaf1 sender pair, 10 moves per flow
  over the 5 flaps.
- "TCP backs off on each flap" would show as RTO counts (`TCPTimeouts`)
  rising by roughly the number of affected flows per flap, and stalls
  getting longer across successive flaps (exponential RTO backoff). I expect
  **partly supported**: RTOs on every down (packets in flight on the dead link
  are lost and the queue drains), but no growth across flaps, because each
  flow recovers within 2 s and the backoff resets on the next ACK.

**Results (2026-10-27 12:03–12:16 EDT).** Flap runs 851–853. Same-day
no-fault control with the same 60 s window and samplers: runs 854–856
(`--injector none`). Per-cycle bins:
[`e8/raw/t4a-flap-bins.txt`](e8/raw/t4a-flap-bins.txt)
(`python fabric/experiments/e8_flap_bins.py`).

| | run 851 | run 852 | run 853 | no-fault 854 / 855 / 856 |
|---|---|---|---|---|
| **full step time** (slowest pair reaches W) | **31.53 s** | **37.68 s** | **31.91 s** | 22.47 / 20.69 / 20.14 s |
| Δ vs E6 baseline 20.0 s | +11.5 | +17.7 | +11.9 | +2.5 / +0.7 / +0.1 |
| pair rate T0+5…25 (all 4 pairs) | ≈ 180–300 Mbit/s | ≈ 120–380 | ≈ 180–310 | ≈ 420–540 |
| full rate again from | ≈ T0+27 | **never in the window** (BGP stall, below) | ≈ T0+27 | — |
| leaf1 eth1 (to spine1) tx in each 2 s up phase | 0 / 0 / 3 / 2 / 0 Mbit/s | 3 / 2 / 2 / 0 / 4 | 0 / 3 / 0 / 3 / 0 | 500 (pre-fault) |
| RTOs (`TCPTimeouts`) per 4 s flap cycle, 4 senders | 71 / 51 / 64 / 93 / 68 | 66 / 89 / 93 / 88 / 53 | 79 / 51 / 95 / 56 / 73 | 9–24 per same window |
| RTOs whole run, host1 / host2 / host3 / host4 | 225 / 186 / 89 / 84 | 413 / 408 / 114 / 146 | 217 / 228 / 93 / 82 | 78 / 77 / 16 / 19; 94 / 85 / 22 / 15; 60 / 53 / 39 / 40 |
| retransmitted segments per 4 s flap cycle | 3,478–4,851 | 3,596–5,789 | 3,510–5,493 | 4,394–8,736 |
| longest stream stall per flap cycle s (streams ≥ 1 s) | 1.0 (3), 0, 0.5, 0.5, 0.5 | 0.5, 0.5, 1.5 (6), 1.5 (2), 0.5 | 1.0 (1), 1.0 (1), 0.5, 0.5, 2.5 (6) | 0 |
| ring flows hashed to spine1 at T0+4 (host1 / host2 / host3 / host4, of 17 sockets each*) | 10 / 7 / 9 / 12 | 8 / 9 / 7 / 9 | 10 / 7 / 5 / 6 | — |
| all-up wait after the run | 2.5 s | **81.2 s** | 2.5 s | — |

\* 16 data streams + iperf3's control connection; `ss` can't tell them
apart.

Flows that change spine per flap. On leaf1 (host1/host2 senders),
`ip monitor` shows the group re-adding spine1 at every up (`id 41 via …
dev eth1`, `id 247 group 38/41`, +15.22 / +19.23 / +23.23 s in run 852).
So the 15–19 leaf1-sourced flows hashed to spine1 move off at each down and
back at each up: 10 moves per flow over the window. On leaf2 (host3/host4
senders toward leaf1), the route monitor shows one change to spine2-only at
T0+5.3 s and one back at T0+26.8 s (runs 851, 853). So the 11–21
leaf2-sourced flows on spine1 move once each way, not per flap.

What the counters say:

1. **For the step, the link is out for the entire 20 s flap window.** In
   the 2 s up phases leaf1 sends 0–4 Mbit/s on eth1 (500 Mbit/s before and
   after). A 2 s up phase is shorter than the ≈ 3 s it takes a returning link
   to carry traffic (§2: DAD + ND + BGP), so ECMP never gets the capacity
   back. All four pairs run at about half rate from T0+5 s to T0+27 s. That
   alone predicts ≈ +11 s (22 s at half rate), and runs 851 / 853 measured
   +11.5 / +11.9 s.
2. **TCP does take RTOs on every flap, at a constant rate.** RTOs per cycle
   are 2–10× the no-fault count in the same windows, mostly on the leaf1
   senders. They don't grow across the five flaps, and per-cycle stalls stay
   at 0.5–2.5 s. Retransmitted segments per cycle are *lower* than with no
   fault (less data in flight at half rate).
3. **Run 852 (+17.7 s) is a different failure.** After the last up, the
   leaf1↔spine1 session stayed in Active (`bgp_bfd_after`: Active on both
   ends; all-up wait 81.2 s → ConnectRetry, §1). The pairs never returned to
   full rate inside the 60 s window: the slowest pair finished at 37.68 s at
   half rate. After T0+30 s, leaf1 sent 1 Mbit/s on eth1. Also, 15 streams
   *into* leaf1 (host3→host2 6/16, host4→host1 9/16) received zero bytes
   from T0+27 to T0+59 s. Yet leaf2's kernel routes to leaf1's prefixes
   were spine2-only the whole time (route monitor). **Why those 15 streams
   stopped is not explained** by the data here (no `ss` on host3/host4). A
   long RTO backoff is the leading candidate; host3/host4 RTOs in this run
   were 114 / 146 vs 82–93 in the others.

**Verdict on "TCP backs off on each flap": not supported as the
explanation of the flap cost.** TCP does take a flat 51–95 RTOs per flap
(2–10× no-fault), but there is no growing back-off. The > +10 s cost is the
link being unusable for the whole window, because each 2 s up phase is
shorter than link bring-up, so ECMP capacity is half for ≈ 22 s. Prediction
check: step 32–36 s predicted, measured 31.5 / 37.7 / 31.9 s (two inside,
852 outside because of the BGP stall). "≈ 16 flows per leaf1 sender move"
predicted, measured 7–10 per sender (15–19 per leaf). "Partly supported"
predicted, measured: RTOs per flap yes, growth no.

### 4b. Link-flap hold-down (EMULATED-POLICY)

**Label: EMULATED-POLICY.** `HOLDDOWN` in [`e8.py`](e8.py) runs inside
spine1 and watches `/sys/class/net/eth1/operstate` every 10 ms. Policy: on
the 2nd carrier-down within 10 s, set spine1:eth1 admin-down and hold it
until 5 s have passed without a flap; then bring it up. It stands in for a
NOS link-flap error-disable with automatic recovery (Cisco IOS / NX-OS
`errdisable detect cause link-flap` + `errdisable recovery cause link-flap`,
Arista EOS `errdisable flap-setting cause link-flap`). It is not a
carrier-delay / debounce timer, which hides short drops but doesn't keep a
flapping port down. Behavioural emulation only, with the 5 s / 10 s values
from the plan, not vendor defaults.

Two differences from 4a, both forced by the policy:

- **Injector moved to the far end.** The hold-down must own spine1:eth1's
  admin state, so the same 5 × (down 2 s / up 2 s) from T0+5 s is driven by
  `ip link set eth1 down/up` on **leaf1**, and spine1 sees carrier loss. Same
  link, same routing effect. To compare like with like, a **control** runs
  the leaf-side injector without the hold-down.
- **Sensing while held.** While spine1 holds eth1 admin-down it can't see
  the far end: a veth, like a port with its laser off, gives no carrier
  signal. So "no flap seen for 5 s" means 5 s held. A down within 10 s of the
  previous one after re-enable starts the next hold.

Commands: `python -m fabric.experiments.e8 flap --label control-leafside --injector leaf1`
then `… --label holddown --injector leaf1 --holddown`, ×3 each.

**Prediction (written before the runs):** with downs at T0+5, 9, 13, 17,
21 and ups at T0+7, 11, 15, 19, 23:

- the policy trips at the 2nd down (T0+9) and holds to T0+14;
- the link returns when leaf1 comes up at T0+15, drops at T0+17 (8 s
  after the previous down, so a hold) and is held to T0+22;
- it comes up for good at T0+23, when leaf1 does.

The last usable up is T0+23 with or without the hold-down. Up phases carry
≈ 0 anyway (4a), so I predict **no step-time gain** (control ≈ hold-down ≈
31–32 s). Fewer flaps reach the routers and TCP (spine1 sees 3 downs, not
5), so fewer RTOs and route changes. Extra time the link is held down while
the far end is up: T0+11–13 and T0+19–21 removed = **≈ 4 s**. The hold-down
would only cut step time if the flapping went on past the point where the
link could have stabilised. With this injector it doesn't.

**Results (2026-10-27 12:19–12:33 EDT).** Control runs 857–859, hold-down
runs 860–862. Bins: [`e8/raw/t4b-flap-bins.txt`](e8/raw/t4b-flap-bins.txt).
Hold-down event log (T0-relative, identical to ±0.05 s in all three runs,
e.g. run 860): `down 5.20, up 7.20, down 9.20 → hold_start 9.20, hold_end
14.20 (far end down), up 15.21, down 17.21 → hold_start 17.21, hold_end
22.21 (far end down), up 23.21`. That is exactly the predicted sequence.

| | control (leaf-side flap) 857 / 858 / 859 | hold-down 860 / 861 / 862 |
|---|---|---|
| **full step time** | **31.50 / 32.35 / 31.28 s** | **33.08 / 32.78 / 32.69 s** |
| Δ vs E6 baseline 20.0 s | +11.5 / +12.4 / +11.3 | +13.1 / +12.8 / +12.7 |
| leaf1 eth1 carries > 200 Mbit/s again from | T0+26.38 / 26.82 / 26.27 | T0+26.96 / 26.08 / 27.19 |
| RTOs, 4 senders, whole run | 787 / 833 / 813 | 551 / 656 / 637 |
| RTOs per cycle T0+13–17 / 17–21 | 130, 107 / 111, 123 / 119, 108 | 44, 53 / 28, 47 / 36, 95 |
| downs reaching the routers | 5 | 3 (T0+5, 9, 17); spine1 held 2 × 5.0 s |
| time held down while the far end was up | — | ≈ 4 s (T0+11–13 and 19–21) |
| all-up wait after the run | 2.5 / 2.6 / 2.4 s | 2.5 / 2.4 / 2.5 s |

Comparison of full step times:

| Condition (E6 W = 1.204 GB, E6 baseline 20.0 s) | Step time | Δ |
|---|---|---|
| E6 dead link (10 s carrier down), E6 runs | 27.40 / 29.10 / 28.13 s | +7.4 / +9.1 / +8.1 s |
| flap, spine-side injector (E6's), 851–853 | 31.53 / 37.68 / 31.91 s | +11.5 / +17.7 / +11.9 s |
| flap, leaf-side injector, control, 857–859 | 31.50 / 32.35 / 31.28 s | +11.3 … +12.4 s |
| flap + hold-down (EMULATED-POLICY), 860–862 | 33.08 / 32.78 / 32.69 s | +12.7 … +13.1 s |

**Verdict: the hold-down does not cut the flap cost here. It costs a bit
(+1.1 s mean, n = 3, inside 2× the run-to-run spread).** It reduces what
TCP and the routers see: 3 downs instead of 5, and 21–32 % fewer RTOs.
Capacity returns at the same moment (T0+26–27 s), because that moment is set
by the far end's last up (T0+23.2 s) plus the ≈ 3 s a returning link needs
(§2). The two 2 s up phases the hold-down removed carried ≈ 0 anyway (4a).
Prediction check: event sequence, ≈ 4 s extra hold, fewer RTOs, and no
step-time gain all as predicted; the +1.1 s loss was not predicted and is
not explained by these counters.

Why the step is still > +11 s although the outage is effectively one 20 s
window: a single 20 s outage at half capacity costs ≈ +10 s by the 4a
arithmetic. The E6 dead-link drill had a 10 s outage, so +7.4–9.1 s is not
the right yardstick for a 20 s flap.

### 4c. Recommendation

**Not supported by data for step time:** a flap hold-down (2nd flap in
10 s → hold until 5 s quiet) didn't shorten a 20 s flap step (+1.1 s, n =
3); it only cut RTOs by 21–32 %. A hold-down pays off only if it ends the
flapping sooner than the far end stops on its own. That needs a fault that
outlasts the hold (not tested), or a hold that keeps the port down until a
human or a longer stability timer clears it.
