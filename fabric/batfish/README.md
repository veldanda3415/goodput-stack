# Offline validation with Batfish (NX-OS render + FRR render)

**Label: OFFLINE-VALIDATED.** The NX-OS configs in
[`../build/example/nxos/`](../build/example/nxos/) were rendered from the same
intent as the lab and checked by Batfish's model. They were **never deployed**:
no NX-OS 9000v, no switch. Batfish models control-plane and forwarding
behavior from configuration text; it does not model BFD timers, buffers, or
hardware.

```bash
make fabric-batfish   # render FRR + NX-OS, start Batfish, run fabric/batfish/tests, stop Batfish
```

Measured on 2026-10-16: `7 passed in 9.06s`; whole target 26 s wall time,
including container start and stop.

## Pins

| Component | Pin | Source |
|---|---|---|
| Batfish server | `docker.io/batfish/allinone:2026.08.27.3685@sha256:54cb0ed94fd9a3c1ca0985f73e5be479e955cee9b9f6a6799b66be3364fd8e5c` | Docker Hub tag list (`hub.docker.com/v2/repositories/batfish/allinone/tags`), read 2026-10-16. This is the only non-`test-` release tag published (also `latest`), so the usual "one release before latest" rule could not be applied |
| pybatfish | `2026.8.19.3660` | PyPI; one before the latest `2026.9.17.3748` ([`requirements.txt`](requirements.txt)) |
| Runtime | rootless Podman, `127.0.0.1:9996/9997` only; container `goodput-batfish`, stopped after the run | [`service.py`](service.py) |

## NX-OS render

[`../render/nxos.py`](../render/nxos.py) renders all six switches from
`fabric/intent/fabric.yaml`: hostname, `feature bgp`/`feature bfd`, loopback0,
routed fabric ports with `bfd interval 100 min_rx 100 multiplier 3` and
`no ip redirects`, rail host-facing ports, eBGP with `timers 3 9` and `bfd` per
neighbor, `maximum-paths 2`, and the same advertised prefixes as FRR. The
NX-OS MTU is capped at 9216 (platform maximum; the lab veths are 9500). EVPN
is not rendered for NX-OS. Golden tests:
[`../tests/test_nxos_render.py`](../tests/test_nxos_render.py).

Citations (in the renderer docstring): Cisco Nexus 9000 NX-OS Unicast Routing
Configuration Guide 10.2(x), *Configuring Advanced BGP* ("Load sharing and
multipath", "BFD", "Configure BGP Interface Peering via IPv6 Link-Local for
IPv4 and IPv6 Address Families"); Cisco tech note 221944 *Configure and
Verify BFD on Nexus 9000 Switches*.

### Unnumbered vs numbered

The renderer produces both variants from one intent. The unnumbered variant
follows the 10.2(x) guide: `neighbor Ethernet1/1 remote-as …`,
`ipv6 address use-link-local-only`, `ipv6 link-local use-bia`, `ip forward`.
The pinned Batfish **does not model it**: every one of those lines is
"This syntax is unrecognized", and `bgpPeerConfiguration` returns **0 peers**
([`results/nxos-unnumbered-attempt.json`](results/nxos-unnumbered-attempt.json)).
So the numbered variant gets a /31 per fabric link from
`address_plan.fabric_p2p: 10.201.0.0/24` in intent.

> **The offline check validates the numbered NX-OS variant; the lab runs unnumbered.**

## Results (NX-OS numbered snapshot)

| Check | Batfish question | Result | Evidence |
|---|---|---|---|
| No parse errors / unrecognized lines | `fileParseStatus`, `initIssues` | 6/6 files `PASSED` (format `CISCO_NX`); 0 init issues | `results/nxos-fileParseStatus.json`, `nxos-initIssues.json` |
| Sessions compatible | `bgpSessionCompatibility` | 16/16 `UNIQUE_MATCH` | `nxos-bgpSessionCompatibility.json` |
| Sessions established | `bgpSessionStatus` | 16/16 `ESTABLISHED` | `nxos-bgpSessionStatus.json` |
| ECMP to every remote leaf loopback and rail prefix | `routes(protocols=bgp)` | every leaf has exactly 2 BGP next hops for each remote loopback and remote host /30 (e.g. leaf1 → 10.200.0.13/32 via `10.201.0.0` and `10.201.0.8`); 120 BGP route rows | `nxos-bgp-routes.json` |
| Rail → rail across spines | `traceroute` from `@enter(leaf1[Ethernet1/3])`, 10.210.0.2 → 10.210.0.10, UDP 4791 | 2 traces, one via spine1 and one via spine2, both `DELIVERED_TO_SUBNET` at leaf2 Ethernet1/3 | `nxos-traceroute-host1-host3.json` |

## Negative tests

**1. leaf1 ASN change (F1's drill, offline).** A scratch copy of the intent sets
leaf1 to AS 65199 (the intent file is untouched).

- The intent validator rejects it first: `leaf ASN must match
  bgp.leaf_asn_base and leaf index`.
- Re-rendering **every** switch from the changed intent is *consistent*. The
  spines' `remote-as` follows, so Batfish shows 16/16 `UNIQUE_MATCH`. Batfish
  checks consistency, not intent.
- F1's actual failure mode is **only leaf1 changed** against the deployed spines.
  A snapshot of new leaf1 + current rest gives `bgpSessionCompatibility`:
  `leaf1 65199 10.201.0.1 → 65000 10.201.0.0 HALF_OPEN`,
  `leaf1 … 10.201.0.8 HALF_OPEN`, `spine1 65000 → 65101 10.201.0.1 HALF_OPEN`,
  `spine2 … HALF_OPEN`; `bgpSessionStatus`: those 4 `NOT_COMPATIBLE`
  (`nxos-neg-asn-*.json`).

| | F1 (FRR lab, after deploy) | F5 (Batfish, before deploy) |
|---|---|---|
| When | after `containerlab restart` of leaf1 | before any device is touched |
| How found | `make fabric-test`: `BGP session down: spine1:eth1 state=Active … 5 failed, 9 passed` | `bgpSessionCompatibility`: 4 sessions `HALF_OPEN`, named by node and IP |
| Cost | outage on leaf1's sessions; recovery waited on FRR's 120 s connect-retry (suite passed after 70 s) | 9 s for the whole Batfish suite; no outage |

**2. `maximum-paths` omitted.** A scratch intent with `ecmp_width: 0` makes the
renderer omit `maximum-paths` (NX-OS default: 1 path). Batfish: leaf1 has
**1** route to 10.200.0.13/32 (`ip 10.201.0.0`) instead of 2
(`nxos-neg-maxpaths-routes.json`). Batfish models this. It does **not** model BFD
timers, so a BFD omission would not appear as a routing difference. MTU
mismatches were not tested.

## Bonus: the lab's own FRR render (unnumbered)

[`frr_snapshot.py`](frr_snapshot.py) wraps each rendered `frr.conf` in
Batfish's Cumulus "concatenated" format (hostname + interfaces + `frr version`)
and adds a `layer1_topology.json` from the intent links, because unnumbered
sessions have no IPs to infer adjacency. Two failures came first: without
`frr version` the FRR section was not parsed at all, and without the Layer-1
file all 16 sessions were `HALF_OPEN` with `Remote_Node: None`. With both:

- `bgpSessionCompatibility`: 16/16 `UNIQUE_MATCH`, `Session_Type
  EBGP_UNNUMBERED`; `bgpSessionStatus` 16/16 `ESTABLISHED`;
- leaf1 → 10.200.0.13/32 via `interface eth1 ip 169.254.0.1` and `eth2`
  (2-way ECMP, as in the lab).
- Files are `PARTIALLY_UNRECOGNIZED`. Batfish does not model the EVPN parts
  (`route-target …`, `vni …`, `attribute-unchanged`, "Route maps on neighbors
  in address-family 'l2vpn evpn' are not supported"), nor `capability
  extended-nexthop`, `bfd`, or `log stdout`. The underlay is validated
  unnumbered; the EVPN overlay is not.

Format docs: <https://batfish.readthedocs.io/en/latest/formats.html> (Cumulus
Linux / concatenated) and the pybatfish Layer-1 topology description.
