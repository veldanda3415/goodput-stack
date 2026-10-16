# ADR 0006 — One intent, many renderers, offline validation before deploy

- **Status:** accepted (2026-10-16)
- **Builds on:** [ADR 0004](0004-fabric-intent-render.md) (vendor-neutral intent → FRR renderer)

## Context

ADR 0004 made `fabric/intent/fabric.yaml` the source of truth and rendered FRR
for the EMULATED lab. Two gaps remained:

1. **One NOS only.** The design goal is a fabric that could be built on
   FRR/SONiC or Cisco NX-OS without redrawing it. Cisco targets matter for the
   roles this work is aimed at.
2. **Errors were found after deploy.** In F1 a leaf ASN change was caught by
   `make fabric-test` only after the leaf restarted. Its sessions stayed down,
   and recovery waited on FRR's 120 s BGP connect-retry
   ([runbook](../../fabric/runbooks/bgp-session-down.md)).

Running NX-OS 9000v in the lab is not possible here (Cisco image download,
RAM), so an NX-OS render can only be validated offline.

## Decision

- **One intent, many renderers.** Each NOS gets a renderer module that reads
  the same validated intent: `render/render.py` + templates (FRR, Linux,
  containerlab), `render/qos.py` (SONiC `config_db` QoS fragments,
  INTENT-ONLY), and now `render/nxos.py` (NX-OS, OFFLINE-VALIDATED). NOS
  syntax lives only in renderers. Each renderer has golden-file tests.
- **Offline validation before deploy.** `make fabric-batfish` renders,
  starts a digest-pinned Batfish container on loopback, and runs pytest checks:
  parse status, BGP session compatibility and establishment, ECMP routes, a
  cross-spine traceroute, and negative tests that must be flagged. Then it
  stops the container. The same check runs on the FRR render, wrapped in
  Batfish's Cumulus format with a Layer-1 topology file.
- **Intent may carry renderer-specific data when a target needs it**, and the
  intent records why. `address_plan.fabric_p2p` (/31 per fabric link) exists
  because the pinned Batfish does not model NX-OS interface (unnumbered)
  peering. The lab still runs unnumbered.
- **Labels stay explicit:** EMULATED (ran in the lab), OFFLINE-VALIDATED
  (checked by Batfish, never deployed), INTENT-ONLY (rendered, never run or
  checked).

## What changes between NOSes and what doesn't

| Aspect | FRR (lab) | SONiC | NX-OS |
|---|---|---|---|
| Topology, ASNs, loopbacks, rails, host prefixes, ECMP width, BFD timers | same intent | same intent | same intent |
| Underlay peering | unnumbered (`neighbor ethN interface`, RFC 8950) | FRR inside SONiC (same) | unnumbered per the 10.2(x) guide, **or** numbered /31s; Batfish only models numbered |
| BFD | `bfd` profile + `neighbor … bfd profile` | FRR | `feature bfd`, interface `bfd interval … min_rx … multiplier …`, `no ip redirects`, `neighbor … bfd` |
| ECMP | `maximum-paths 2` + Linux hash sysctl | ASIC hash config | `maximum-paths 2` + hardware hash (not rendered) |
| QoS / lossless | Linux `tc` (classification only) | `config_db` QoS (INTENT-ONLY) | not rendered |
| EVPN tenants | rendered and run (E7) | not rendered | not rendered (optional, left out) |
| MTU | 9500 veth | — | capped at 9216 (platform max) |

## Results that support the decision

- NX-OS numbered render: 6/6 files parse cleanly; 16/16 sessions
  `UNIQUE_MATCH` and `ESTABLISHED`; 2 ECMP paths to every remote leaf prefix;
  a traceroute uses both spines ([`fabric/batfish/README.md`](../../fabric/batfish/README.md)).
- The F1 ASN drill, offline: a partial change (leaf1 only) gives 4 `HALF_OPEN`
  / `NOT_COMPATIBLE` sessions in 9 s, before deploy and without an outage. A
  consistent full re-render is *not* a BGP fault; the intent validator
  rejects it instead (ASN must equal `leaf_asn_base` + index). Batfish checks
  consistency between configs, and the validator checks the plan.
- `maximum-paths` omission: Batfish shows 1 path instead of 2.
- The lab's unnumbered FRR underlay: 16/16 sessions `EBGP_UNNUMBERED`
  established in Batfish once a Layer-1 topology is supplied. The EVPN
  overlay is not modeled (RTs, VNIs, `attribute-unchanged` unrecognized).

## Alternatives considered

- **Hand-written NX-OS configs.** Rejected: a second source of truth for the
  same topology, the failure ADR 0004 avoids.
- **Run NX-OS 9000v in containerlab.** Not possible here (licensing/download
  and memory). It would add data-plane/runtime validation; Batfish does not
  replace it.
- **Deploy-and-test only (F1's method).** Kept, but as the second gate:
  post-deploy tests catch what models miss (timers, BFD, EVPN, MTU, real
  convergence, e.g. E6's restore transients).
- **Render unnumbered NX-OS and skip validation.** Rejected: unvalidated config
  is worse than validated config with a stated variant gap.

## Production equivalent

- **Source of truth:** NetBox or Nautobot holding devices, links, ASNs, and
  prefixes, exported to (or replacing) `fabric.yaml`; renderers run in CI
  (Nornir/Ansible/Jinja) and produce per-device configs as reviewable diffs.
- **Pre-deployment gate:** Batfish in CI on every intent or renderer change.
  It checks sessions, routes, reachability and ACLs against the *planned*
  snapshot and blocks merge on regressions. It also diffs the planned
  snapshot against a snapshot of the *running* configs, which is how F1's
  partial-change fault is caught.
- **Rollout:** canary one leaf or one spine, run post-deploy checks
  (`fabric-test`-style: sessions, BFD, ECMP, reachability, tenant isolation),
  watch the telemetry signals (E6), then continue or roll back.

## Consequences and limits

- Every new NOS costs a renderer, golden tests, and a statement of which
  validator models which features. A Batfish gap is recorded, not papered over.
- OFFLINE-VALIDATED is not "works on NX-OS": no timer, BFD, hardware, or
  software-bug behavior is tested. The numbered NX-OS variant differs from the
  lab's unnumbered underlay.
- Batfish pins: `batfish/allinone:2026.08.27.3685@sha256:54cb0ed9…e5c` (the
  only release tag on Docker Hub, so not one-before-latest); pybatfish
  2026.8.19.3660.
