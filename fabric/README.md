# EMULATED AI fabric

This track keeps [`intent/fabric.yaml`](intent/fabric.yaml) as the vendor-neutral
source of truth. The Python renderer validates it, then generates FRR
configurations, host setup scripts, and a containerlab topology. FRR is
integrated and configured here; it is not software built by this project.

## Run the lab

Requirements: Python 3, Podman, and containerlab. The validated environment
used Python 3, containerlab 0.78.2, and Podman 5.7.0. Use the native
`containerlab --runtime podman` path: the
[containerlab v0.78.2 deploy documentation](https://github.com/srl-labs/containerlab/blob/v0.78.2/docs/cmd/deploy.md#runtime)
documents Podman support as experimental, and this lab deployed successfully
with it. In the recorded environment `podman info` reported `rootless=true`;
the rootful socket at `/run/podman/podman.sock` was inaccessible. No Docker
Engine was used.

```bash
make fabric-render  # validate intent; render FRR and containerlab files
make fabric-up      # render, then deploy the EMULATED lab
make fabric-test    # validate the running lab; run after fabric-up
make fabric-e1      # ECMP hash policy experiment
make fabric-e2      # BFD convergence experiment
make fabric-down    # destroy the lab
```

`make fabric-up` leaves the lab running. `make fabric-down` removes it.
Generated files are in ignored `fabric/build/`; `fabric/build/example/` is the
committed review render. Rendering the same intent is byte-deterministic.
Focused tests: `make fabric-test`; this runs pytest in `fabric/tests/`.

The FRR image is pinned to
[`quay.io/frrouting/frr:10.2.1`](https://quay.io/repository/frrouting/frr)
with its digest. The host image is the locally built RDMA tools image
(`localhost:5000/goodput-roce-host:0.1.0`, also pinned by digest), described
in the RDMA section below. It replaced `nicolaka/netshoot:v0.13`. All full
image references are in the intent. FRR configuration uses
the stable 10.2 [BGP](https://docs.frrouting.org/en/stable-10.2/bgp.html) and
[BFD](https://docs.frrouting.org/en/stable-10.2/bfd.html) documentation.

## Topology and address plan

The lab is two spines, four leaves, and four dual-NIC Linux hosts. Spine AS
65000 connects to leaf ASes 65101–65104. Each leaf has one link to each spine;
two equal-cost paths provide ECMP. Hosts 1–2 attach to leaves 1 and 3, and
hosts 3–4 to leaves 2 and 4: NIC0 is rail A and NIC1 rail B. eBGP uses IPv6
link-local neighbors; IPv4 routes are advertised with IPv6 next hops using
the extended-next-hop capability. BFD is configured on fabric links.

| Use | Prefix | Notes |
|---|---|---|
| Router loopbacks | `10.200.0.0/24` | one `/32` per router |
| Host-facing networks | `10.210.0.0/16` | eight `/30`s across rails A and B |
| Containerlab management | `10.253.0.0/24` | isolated lab management network |
| Excluded ranges | `10.42.0.0/16`, `10.43.0.0/16`, `10.89.0.0/24` | k3s pod/service and Podman bridge ranges |

Fabric links use IPv6 link-local addresses and need no IPv4 point-to-point
subnets. The intent validator checks unique leaf ASNs, endpoint references,
subnet overlap, and exactly one host NIC per rail before rendering.

Hosts have per-NIC source-policy routing so replies use the rail that owns the
source address. Loose reverse-path filtering (`rp_filter=2`) allows valid
asymmetric return paths through ECMP; routers disable reverse-path filtering.
See [bring-up evidence](results/f1-bringup.md) for verified commands and
outputs.

## Experiments and evidence

- [F1 bring-up](results/f1-bringup.md): BGP/BFD state, IPv4 routes over IPv6
  next hops, two-way ECMP, host reachability, traceroute, and observed
  bring-up time.
- [E1 — ECMP hash policy](experiments/E1-ecmp-hash.md): one, four, and 32
  flows under Linux L3 and L4 hash policies; splits come from leaf interface
  byte-counter deltas.
- [E2 — BFD convergence](experiments/E2-bfd-convergence.md): carrier-down
  and silent-loss trials with BFD on and off; loss windows come from timestamped
  ping replies and sequence numbers.
- [E3 — Soft-RoCE and RoCE QoS](experiments/E3-soft-roce.md): feasibility
  of rxe in container namespaces (blocked by the kernel), GID selection,
  QoS render, host DSCP classification, and headroom.
- [BGP session-down runbook](runbooks/bgp-session-down.md): observed ASN
  mismatch symptoms and recovery.

All results are **EMULATED**: containerlab veth links and Linux kernel
forwarding. The lab does not model switch ASICs or claim line-rate performance.
BGP, ECMP, and BFD control-plane design and failure logic transfer as concepts
to real switches, subject to vendor-specific configuration and validation.
E1 measures Linux kernel hashing, not ASIC hashing. This work does not
demonstrate hardware buffers, PFC, DCQCN, RoCE congestion control, or production
convergence. No NOS VMs or GPUs are used.

## RDMA (SOFT-ROCE) and QoS intent

Hosts run a pinned RDMA tools image, built from
[`images/roce-host/Containerfile`](images/roce-host/Containerfile) (Debian
trixie by digest; packages pinned from snapshot.debian.org). containerlab is
setuid root and uses the system Podman, so the image is served from a
localhost registry. Root Podman must trust that registry; this takes one
`registries.conf.d` entry, set up with sudo. The exact steps are in
[E3](experiments/E3-soft-roce.md).

```bash
make roce-image       # start the localhost:5000 registry; build and push the host image
make fabric-up        # renders rxe devices (rxe_<host>_<rail>) and host tc QoS
make roce-e3          # GID discovery + DSCP classification counters
make fabric-headroom  # PFC headroom table (INTENT-ONLY arithmetic)
```

The intent controls each deployed piece. `rdma` creates one `rdma_rxe` device
per rail NIC, and `capture_taps` adds `spineN-tap` sidecars that share the
spine's network namespace so capture tools can run there. `qos` holds the
lossless RoCE design.

| Piece | Status |
|---|---|
| rxe devices, GIDs (`::ffff:<rail IP>`, RoCE v2, index 1) | SOFT-ROCE, works |
| Verbs traffic across the fabric | **does not work on Linux 6.18**: rxe routes and receives only in the initial netns ([E3 §0](experiments/E3-soft-roce.md#0-feasibility-gate)) |
| SONiC `config_db` QoS fragments (`build/example/sonic/`) | INTENT-ONLY, never run on a switch |
| Host `tc` DSCP classification (`hosts/<host>-qos.sh`) | EMULATED, verified with counters; no PFC, buffers, or ECN on veth |
| PFC headroom (`tools/headroom.py`) | INTENT-ONLY arithmetic with cited sources |

Design and sources: [`qos/README.md`](qos/README.md).

## Production path

Keep the intent model as the design source of truth. A production deployment
could populate it from NetBox or Nautobot, render device configuration with
Nornir or Ansible, run Batfish pre-checks, and use a staged canary rollout.
Those integrations are future work; the current renderer targets FRR only.
See [ADR 0004](../docs/adr/0004-fabric-intent-render.md) for the decision and
protocol rationale.
