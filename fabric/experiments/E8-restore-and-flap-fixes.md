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
