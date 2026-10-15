# ADR 0004 — Vendor-neutral fabric intent and renderer

- **Status:** accepted (2026-10-15)

## Context

The AI-fabric track needs an executable leaf-spine design, repeatable lab
configuration, and checks that catch topology mistakes before deployment.
Hand-maintained FRR files and a separately maintained containerlab topology
would duplicate device identities, links, addresses, and routing parameters.
They could drift while still appearing individually valid.

The first target is an EMULATED containerlab lab: two spines, four leaves, and
four dual-rail Linux hosts. It is not a production lossless fabric.

## Decision

Keep `fabric/intent/fabric.yaml` as a vendor-neutral topology and protocol
model. Validate the model's schema and graph semantics before producing any
configuration. The renderer generates per-node FRR files, host network setup,
and a containerlab topology under ignored `fabric/build/`; it also updates a
committed example render for review. Rendering must be deterministic.
Pytest covers schema/semantic checks, generated artifacts, and the live lab.

FRR commands belong only in the renderer templates, never in the intent.
The renderer currently supports FRR; SONiC and NX-OS are future renderer
targets, not implemented capabilities.

## Alternatives

- **Hand-write FRR and containerlab files.** Rejected because duplicated
  topology data can silently diverge, and generated changes are harder to
  review consistently.
- **Use a vendor-specific configuration as the source of truth.** Rejected
  because it would couple the design model to one NOS and make cross-vendor
  validation and rendering more difficult.
- **Generate configs without validating the topology first.** Rejected because
  missing endpoints, duplicate leaf ASNs, overlapping subnets, or a missing
  host rail should fail before any deployment.

## Routing design

Use single-hop eBGP over directly connected IPv6 link-local addresses on
fabric links. This avoids allocating and tracking an IPv4 `/31` for each
point-to-point link. Exchange IPv4 routes with IPv6 next hops by negotiating
the extended-next-hop capability specified by
[RFC 8950](https://www.rfc-editor.org/rfc/rfc8950.html); this lets the
underlay use link-local IPv6 for next-hop resolution without changing the
host-facing IPv4 addressing.

All spines use AS 65000; leaves use unique ASNs 65101–65104. This follows the
Clos guidance in [RFC 7938 §5.2.1](https://www.rfc-editor.org/rfc/rfc7938.html#section-5.2.1):
one ASN for all Tier 1 devices and a unique ASN for each Tier 3 device. It
also gives both spine paths the same AS-path structure for a given leaf
prefix, which supports equal-cost multipath. RFC 7938 §5.1 describes how a
well-defined ASN allocation and standard AS-path loop detection control BGP
path hunting and reject unwanted paths; §6.2 discusses ECMP across multiple
ASNs. In this two-tier underlay the intended leaf-to-leaf route is a simple
leaf–spine–leaf path; the shared spine AS and unique leaf ASes preserve that
valley-free structure rather than creating artificial inter-spine AS hops.
The two-spine lab installs two equal-cost paths to remote leaves.

The lab additionally configures BFD on fabric links and maximum-paths for
ECMP. These choices and their observed behavior are documented in the
[bring-up evidence](../../fabric/results/f1-bringup.md) and
[experiments](../../fabric/experiments/).

## Production equivalent

Keep the intent model as the reviewed source of truth, populated from an
inventory system such as NetBox or Nautobot. A production pipeline could use
Nornir or Ansible renderers, Batfish pre-checks, and a staged canary rollout
with explicit post-deploy verification and rollback criteria. That pipeline
is future work; this repository currently renders FRR for the emulated lab.

## Consequences and limits

- Topology validation, generated configuration, and tests share one model.
- Re-rendering is reproducible, and generated config diffs remain reviewable.
- A new NOS requires a renderer and its own syntax/capability validation.
- The containerlab results are EMULATED: veth links and Linux kernel
  forwarding. They validate control-plane concepts and software behavior, not
  switch ASIC forwarding, buffers, PFC, DCQCN, ASIC hashing, RoCE performance,
  or line rate. Production behavior and timing must be tested on the target
  hardware and NOS.
