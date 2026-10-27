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
documents Podman support as experimental. `/usr/bin/containerlab` is setuid
root, so it uses the system/rootful Podman service; a rootless `podman info`
does not describe the lab runtime. No Docker Engine was used.

```bash
make fabric-render  # validate intent; render FRR and containerlab files
make fabric-up      # render, then deploy the EMULATED lab
make fabric-status  # read-only: is the lab up, BGP/BFD, shaping, hash policy, telemetry, Batfish
make fabric-test    # validate the running lab; run after fabric-up
make fabric-e1      # ECMP hash policy experiment
make fabric-e2      # BFD convergence experiment
make roce-vm-image  # build and publish the pinned QEMU runner image
make roce-vm-up     # deploy the EMULATED lab with two SOFT-ROCE VM endpoints
make fabric-e3      # E3 VM verbs, wire decode, and QoS checks
make fabric-e4      # E4 EMULATED RED/ECN bottleneck experiment
make fabric-e5      # E5 collective-shaped traffic / ECMP entropy sweep
make telemetry-up   # local Prometheus + EMULATED Linux fabric exporter
make telemetry-down # stop those local telemetry services
make fabric-shape-on      # EMULATED: TBF 500 Mbit/s on both ends of every leaf-spine veth
make fabric-shape-off     # remove shaping and any even-split pins
make fabric-shape-status  # shaped ports and pin rules
make fabric-e5-shaped     # E5 rerun with shaped uplinks + measured even-split baseline
make fabric-e6            # E6 failure drills under collective load (shaped)
.venv/bin/python -m fabric.experiments.e6_restore --repeats 3   # E6: instrumented spine restore (shaped)
.venv/bin/python -m fabric.experiments.e6_restore_report        # its per-run restore timeline
make fabric-e7            # E7 EVPN-VXLAN tenant evidence + trap drills
.venv/bin/python -m fabric.experiments.e8 restore|flap|jobs|degrade ...   # E8 (shaped; see E8 doc)
make fabric-batfish       # render NX-OS (+FRR) and validate OFFLINE with Batfish
make fabric-down    # destroy the lab
```

Result labels used throughout: **EMULATED** (veth + kernel forwarding),
**SOFT-ROCE** (rdma_rxe), **VM** (QEMU guest), **INTENT-ONLY** (rendered,
never run), **OFFLINE-VALIDATED** (checked by Batfish, never deployed).
Emulated throughput is never switch or NIC performance.

`make fabric-up` leaves the lab running. `make fabric-down` removes it.
Generated files are in ignored `fabric/build/`; `fabric/build/example/` is the
committed review render. Rendering the same intent is byte-deterministic.
Focused tests: `make fabric-test`; this runs pytest in `fabric/tests/`.
65 tests, 11 of them need the running lab (`test_running_lab.py` and the
five `# ---- running lab` tests in `test_tenants.py`). With the lab down there
is no marker; run the other 54 with
`pytest fabric/tests --ignore=fabric/tests/test_running_lab.py -k 'not reach and not isolated and not route_targets and not path_mtu'`.
The lab tests fail rather than pass when the lab is down: the tenant isolation
checks no longer treat "containerlab exec failed" as "unreachable".

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
| Front-end tenants | `10.220.0.0/16` | EVPN-VXLAN tenant VRF subnets, one /24 per tenant per leaf (E7) |
| Fabric /31 pool | `10.201.0.0/24` | numbered NX-OS render only; the lab runs unnumbered |
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
- [E3 — Soft-RoCE and RoCE QoS](experiments/E3-soft-roce.md): VM-backed
  SOFT-ROCE RC traffic across a spine, wire decode, DSCP/ECN, and the
  container-host namespace limitation.
- [E4 — ECN marking](experiments/E4-ecn.md): intent-scaled Linux RED on an
  EMULATED bottleneck, TCP ECN on/off, and SOFT-ROCE packet marking.
- [E5 — collective traffic and ECMP entropy](experiments/E5-collective-entropy.md):
  ring/all-to-all TCP sweeps and supplemental SOFT-ROCE QP measurements.
- [E5 shaped rerun](experiments/E5-collective-entropy.md#shaped-uplinks-rerun):
  uplinks shaped to 500 Mbit/s (`lab_shaping` in intent, 1/20 of measured
  per-host throughput); synchronized start, receiver last-byte timing, and
  a measured even-split baseline (per-pair pins rendered from intent). Job
  time tracked the busiest link (r = 0.998). Ring with an L3 hash took ≈ 2×
  the even split; L4 at 16 flows/pair came within +0.03 s.
- [E6 — failure drills](experiments/E6-failure-drills.md): link down, silent
  loss, flap, spine loss, leaf loss, and 1% silent degradation under a shaped
  ring collective, with per-rail/per-tenant blast radius, FIB reconvergence
  timestamps, and telemetry-based detection of the degraded link (partial:
  2/3 runs).
- [E6 restore transient](experiments/E6-failure-drills.md#restore-transient):
  instrumented spine-loss restore (×3, one clock). zebra puts the restored
  spine back in the leaves' kernel ECMP group at link-up (+0.2 s), before
  BGP is up. Loss starts when the leaf resolves the spine's link-local
  address and ends when the spine's FIB has the route (1.3–1.6 s on rail B).
  `bgp update-delay` doesn't apply (process restart only). H2 tested and
  fixed in E8.
- [E8 — restore and flap fixes](experiments/E8-restore-and-flap-fixes.md):
  timer/DAD audit; H2 confirmed (zebra reinstalls its kept nexthop group at
  link-up); `no zebra nexthop kernel enable` on the leaves cut spine-restore
  loss to 0 in 3 / 3 runs; flap step 31.5–37.7 s with an EMULATED-POLICY
  hold-down giving no gain; DAD-off and spine `coalesce-time` don't shrink the
  window; a rail-B job is unaffected by leaf1 loss; 1 % loss cost follows the
  uplink, not the flow count.
- [E7 — EVPN-VXLAN tenancy](experiments/E7-evpn-tenancy.md): two tenant VRFs
  (symmetric IRB, explicit RTs, anycast gateway MAC) on the front end;
  reachability, isolation (including two tenants on one leaf), VNI captures,
  and drills for the RT, next-hop, and MTU traps.
- [Batfish offline validation](batfish/README.md): NX-OS render (numbered)
  and the lab's FRR render (unnumbered), with negative tests caught before deploy.
- [Runbooks](runbooks/README.md): nine runbooks, six measured in this lab.
- [Fabric telemetry](telemetry/README.md): the local Python/Prometheus
  fallback, dashboard, exported panel evidence, and the incomplete gNMI
  attempt.
- [BGP session-down runbook](runbooks/bgp-session-down.md): observed ASN
  mismatch symptoms and recovery.

The base fabric results are **EMULATED**: containerlab veth links and Linux
kernel forwarding. E3/E4/E5 separately label **SOFT-ROCE** measurements,
which run `rdma_rxe` in VM guest kernels over the same EMULATED veth fabric.
QoS device configuration and physical headroom/PFC settings are
**INTENT-ONLY**. No result claims switch ASIC behavior or line-rate
performance.
BGP, ECMP, and BFD control-plane design and failure logic transfer as concepts
to real switches, subject to vendor-specific configuration and validation.
E1 measures Linux kernel hashing, not ASIC hashing. This work does not
demonstrate hardware buffers, PFC, DCQCN, or production convergence.

## RDMA (SOFT-ROCE) and QoS intent

Container hosts run a pinned RDMA tools image, built from
[`images/roce-host/Containerfile`](images/roce-host/Containerfile) (Debian
trixie by digest; packages pinned from snapshot.debian.org). containerlab is
setuid root and uses the system Podman, so the image is served from a
localhost registry. Root Podman must trust that registry; this takes one
`registries.conf.d` entry, set up with sudo. The exact steps are in
[E3](experiments/E3-soft-roce.md).

```bash
make roce-image       # start the localhost:5000 registry; build and push the host image
make roce-vm-image    # build and push the pinned QEMU VM runner image
make roce-vm-up       # deploy; VM endpoints run rxe in their own guest kernels
make fabric-e3        # cross-spine RC verbs + wire decode, plus devices/QoS checks
make roce-e3          # focused container-host devices/GIDs + DSCP classification check
make fabric-headroom  # PFC headroom table (INTENT-ONLY arithmetic)
```

The intent controls each deployed piece. `rdma` creates one `rdma_rxe` device
per container-host rail NIC, and `capture_taps` adds `spineN-tap` sidecars
that share the spine's network namespace so capture tools can run there.
`vm_hosts` defines two QEMU-backed endpoints: 768 MiB and 2 vCPUs each,
connected on rail A to leaf1 and leaf2. On the measured WSL2 host `/dev/kvm`
was available and both guests used KVM; the runner falls back to TCG if KVM
is unavailable. Guest image checksum, package snapshots, image digests, and
source references are recorded in [E3](experiments/E3-soft-roce.md).
`qos` holds the lossless RoCE design.

| Piece | Status |
|---|---|
| Container-host rxe devices, GIDs (`::ffff:<rail IP>`, RoCE v2, index 1) | SOFT-ROCE device setup works; verbs packet I/O is blocked by Linux 6.18 `init_net` routing/socket behavior ([E3 §0](experiments/E3-soft-roce.md#0-feasibility-gate)) |
| VM-backed verbs traffic across the fabric | **SOFT-ROCE + EMULATED, works**: two guest kernels complete RC `ib_write_bw`/`ib_read_lat` and iperf3 cross-spine runs ([E3 §1](experiments/E3-soft-roce.md#1-rdma-across-the-fabric--complete-soft-roce--emulated)) |
| SONiC `config_db` QoS fragments (`build/example/sonic/`) | INTENT-ONLY, never run on a switch |
| Host `tc` DSCP classification (`hosts/<host>-qos.sh`) | EMULATED, verified with counters; not switch QoS, PFC, or buffers |
| Linux RED/ECN bottleneck | EMULATED `tc` qdisc; E4 measures TCP marks and SOFT-ROCE CE packets, not switch ECN/DCQCN |
| PFC headroom (`tools/headroom.py`) | INTENT-ONLY arithmetic with cited sources |

**Soft-RoCE in containers ([gaps](../docs/gaps.md#fabric-rdma-and-roce)):** VM endpoints resolve the experiment blocker by giving each
`rdma_rxe` device its own kernel's initial network namespace. The original
container-host rxe endpoints remain unable to send on this WSL2 Linux 6.18
kernel; this is not a kernel namespace fix.

Design and sources: [`qos/README.md`](qos/README.md). E3, E4, and E5 include
predictions before each measurement and retain the commands/raw evidence.
SOFT-ROCE throughput is CPU-bound software performance and must never be
presented as NIC throughput.

## Telemetry

`make telemetry-up` starts a host-side Python exporter for Linux leaf
interface/qdisc counters and FRR BGP/BFD state, plus a standalone,
digest-pinned Prometheus container. This telemetry is **EMULATED**, not
switch ASIC data. It does not alter the existing k3s installation; Prometheus
is local to the lab host and listens on `127.0.0.1:9098`. Import
[`../observability/dashboards/fabric.json`](../observability/dashboards/fabric.json)
for uplink rates, per-leaf imbalance, discards, qdisc ECN marks, and BGP/BFD
state. [`telemetry/README.md`](telemetry/README.md) records the exporter pin
and evidence.

The SR Linux/gNMI path is **not complete**: the pinned Nokia SR Linux
containerlab attempt failed before a gNMI subscription could run. The
dashboard and E5 panel export use the Python exporter fallback; none of its
metrics should be described as gNMI data.

## Shaped profile, tenants, NX-OS (F5)

- **Shaped profile.** `lab_shaping` in intent renders
  `fabric/build/shaping/<router>-shape-{on,off}.sh` (TBF `rate 500mbit burst
  125000 limit 625000` on both ends of every leaf↔spine veth) and per-pattern
  even-split pins (`<leaf>-pin-{ring,all-to-all}.sh`, both directions of a
  host pair on the same spine). `make fabric-shape-on/off` applies them at
  runtime without touching BGP/BFD. Use it whenever the fabric, not the host
  containers, must be the bottleneck (E5 shaped, E6).
- **Tenants.** `tenants:` in intent renders FRR EVPN on leaves and spines, plus
  a two-stage Linux script per leaf (`tenants/<leaf>-tenant-devices.sh` runs
  before FRR starts; `-ports.sh` enslaves the containerlab ports and checks
  the L3VNI route targets). It also adds five pinned netshoot endpoints (ta1,
  ta3, tb1, tb2, tb4). Fabric links get an explicit `mtu: 9500`; tenant MTU
  9000.
- **NX-OS.** `python -m fabric.render.nxos` renders all six switches from the
  same intent (numbered and unnumbered variants) into `build/nxos/`.
  `make fabric-batfish` validates them offline (pinned Batfish, started and
  stopped by the target). See [ADR 0006](../docs/adr/0006-multi-nos-render-batfish.md).

`make fabric-test` covers intent/render checks, shaping and NX-OS render
golden tests, and the running lab, including tenant reachability and
isolation and per-VNI route targets (65 checks).

## Production path

Keep the intent model as the design source of truth. A production deployment
could populate it from NetBox or Nautobot, render device configuration with
Nornir or Ansible, run Batfish pre-checks, and use a staged canary rollout.
Batfish pre-checks now exist for the NX-OS and FRR renders
([ADR 0006](../docs/adr/0006-multi-nos-render-batfish.md)); NetBox/Nautobot,
Nornir/Ansible, and canary rollout remain future work.
See [ADR 0004](../docs/adr/0004-fabric-intent-render.md) for the decision and
protocol rationale.
