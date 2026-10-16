# E3 — Soft-RoCE across the fabric and lossless RoCE QoS

**Status (2026-10-15):** RDMA verbs traffic across the fabric is **not
feasible on this kernel**. The cause is identified below, and the RDMA
measurements and RoCE wire decode were not run. The QoS design is rendered
(**INTENT-ONLY**), and host-side DSCP classification is verified in the lab
(**EMULATED**).

Labels used here:

- **EMULATED**: containerlab veth links and Linux kernel forwarding.
- **SOFT-ROCE**: `rdma_rxe`, software RoCE v2. It is CPU-bound and has no
  DCQCN and no PFC.
- **INTENT-ONLY**: rendered configuration that has never run on hardware.

## 0. Feasibility gate

### What the lab actually runs on

`/usr/bin/containerlab` is setuid root (`-rwsr-xr-x root`), so `containerlab
--runtime podman` drives the **system (rootful) Podman socket**
(`podman.socket`, active). The lab containers do not appear in the user's
rootless `podman ps`. The earlier note that the lab runs rootless describes
the user's CLI, not the lab runtime. Option (c), "run rootful", was therefore
already the case.

### Steps and results

| Step | Command (in host1 unless noted) | Result |
|---|---|---|
| Module on WSL host | `lsmod \| grep rdma_rxe` | `rdma_rxe 180224 0`; `ib_uverbs`, `ib_core` loaded |
| RDMA netns mode | `rdma system show` | `netns shared privileged-qkey off ...` |
| Capabilities | `grep CapEff /proc/self/status` | `000001ffffffffff` (privileged, rootful) |
| Option (a): rxe inside the container | `rdma link add rxe_h1a type rxe netdev eth1` (netshoot + `apk add iproute2-rdma`, test only) | **succeeded**; `rdma link show` → `rxe_h1a/1 state ACTIVE ... netdev eth1` |
| Verbs device in the container | `ibv_devices` after deploy | rxe device missing at first; fixed (see Failures) |
| GID table | `ibv_devinfo -v -d rxe_host1_a` | GID[0] `fe80::a8c1:abff:fe2a:a554` RoCE v2; **GID[1] `::ffff:10.210.0.2` RoCE v2** |
| Verbs traffic | `ib_write_bw -d rxe_host1_a -x 1 -s 65536 -n 100 -F --bind_source_ip 10.210.0.2 10.210.0.6` (server on host2: `ib_write_bw -d rxe_host2_a -x 1 -s 65536 -n 100 -F`) | **failed**: `Completion with error at client` / `Failed status 5: wr_id 0 syndrom 0x0` / `scnt=100, ccnt=0` |

GID index choice: rxe derives GIDs from the addresses of its netdev. The RoCE
v2 GID for a rail is the IPv4-mapped address `::ffff:<rail IPv4>`, and it is
index 1 on all eight devices (`fabric/experiments/e3-results.json`,
`devices`). The driver selects it by matching that address and type `RoCE v2`
in `ibv_devinfo -v`; it does not hard-code the index.

### Why verbs traffic fails: rxe is bound to the initial network namespace

Counters around the failing run, from `rdma statistic show link <dev>/1`,
`ip -s -j link show dev eth1`, and `/proc/net/snmp`. Raw values are in
`e3-results.json` under `feasibility_failure`.

| | host1 (client) | host2 (server) |
|---|---:|---:|
| rxe `sent_pkts` delta | **0** | 0 |
| rxe `rcvd_pkts` delta | 0 | 0 |
| eth1 TX / RX packet delta | 12 / 10 | 10 / 12 |
| UDP `NoPorts` (cumulative since deploy) | 0 | 15 |

The two QPs exchanged connection data over perftest's TCP side channel,
which accounts for the ~10 eth1 packets each way. The rxe device on host1
then transmitted **zero** RoCE packets, and the work requests were flushed.
host2's 15 UDP `NoPorts` accumulated during the first attempted run after
deploy. That fits RoCE datagrams reaching host2's namespace with nothing
listening on UDP 4791, but that attribution was not isolated.

The kernel source explains both directions. Tree: `~/src/wsl-kernel`, tag
`linux-msft-wsl-6.18.33.2`, `drivers/infiniband/sw/rxe/rxe_net.c`:

- line 37: `rt = ip_route_output_key(&init_net, &fl);`. The IPv4 route for
  a RoCE packet is looked up in the **initial** namespace (the WSL VM), not
  in the container that owns `eth1` and its policy-routing tables.
- lines 633 and 648: `recv_sockets.sk4/sk6 = rxe_setup_udp_tunnel(&init_net, ...)`.
  The UDP 4791 receive socket exists only in the initial namespace.

`rdma system` "shared" mode only makes the RDMA *device* visible in every
namespace; it does not move rxe's packet I/O. Options (a) and (b) both leave
the netdev in the container netns, so both fail the same way. Option (c),
rootful, is already in use. **Per (d), RDMA work stopped here**, and Tasks
3–4 were completed.

Possible ways forward, untested:

1. A kernel whose rxe has network-namespace support. Check the upstream rxe
   history before relying on any particular version.
2. Put the RDMA endpoints in the initial namespace: rxe on veths whose host
   end stays in the WSL root namespace, routed into the fabric. This needs
   root on the WSL host for each veth and route.
3. A real RoCE NIC with SR-IOV VFs moved into the containers.

### Image and runtime pins

| Item | Pin | Source |
|---|---|---|
| Host image base | `docker.io/library/debian:trixie-20260918-slim@sha256:7792b1f7702a86946cd518db72b6a407302c3e9bc1635634368b878189e8221c` | Docker Hub `library/debian` tags; release before the newest dated tag `trixie-20261005` |
| apt source | `snapshot.debian.org/archive/debian/20260918T000000Z` (+ `-security`, `trixie-updates`) | <https://snapshot.debian.org/> |
| Packages | `rdma-core`, `ibverbs-utils`, `ibverbs-providers`, `rdmacm-utils` `56.1-1`; `perftest 25.01.0+0.80-1`; `iproute2 6.15.0-1`; `iperf3 3.18-2+deb13u2`; `tcpdump 4.99.5-2`; `tshark 4.4.18-0+deb13u1`; `sysstat 12.7.5-2`; `procps 2:4.0.4-9`; `iputils-ping 3:20240905-3`; `traceroute 1:2.1.6-1` | `apt-cache policy` against the snapshot, verified with `dpkg-query -W` in the built image |
| Host image | `localhost:5000/goodput-roce-host:0.1.0@sha256:f6f2f4045e4f9a533cebb4435c8acc8f7182104d1dca19bf033f50455d0056e2` | `fabric/images/roce-host/Containerfile`; digest of the pushed manifest (rebuilds are not byte-identical; update intent after `make roce-image`) |
| Local registry | `docker.io/library/registry:3.1.1@sha256:3d527cee870ddd0fc8a31f99b2fdfb6451801a8dd4f5a92c1ec36dae24c14274` | Docker Hub `library/registry`; release before `3.1.2` |
| Root Podman trust | `/etc/containers/registries.conf.d/50-goodput-local.conf`: `[[registry]] location = "localhost:5000" insecure = true` | Created by the user with sudo; containerlab 0.78.2 accepts only `docker://` references (`Unsupported transport oci-archive ... only docker transport is supported`) |

After the image change, `make fabric-up` and `make fabric-test` ran:
**29 passed**. These are the original 14 checks (9 intent and 5 live-lab
tests) plus 15 new tests for QoS, headroom, and the decoder.

## 1. RDMA across the fabric — not run

Blocked by §0. `ib_write_bw`/`ib_read_lat` and iperf3 comparisons on the
same-leaf (host1 A ↔ host2 A, both on leaf1), cross-spine (host1 A ↔ host3
A), and cross-rail (host1 A ↔ host3 B) paths are implemented in
`fabric/experiments/e3/run.py rdma`, but **no results exist**.

On a working kernel, Soft-RoCE would prove the following: the verbs API, QP
and MR setup, RoCE v2 routed as ordinary UDP/IP over the BGP L3 fabric, and
ECMP selection by UDP source port. It would not prove NIC throughput,
latency, losslessness, or congestion control (rxe has no DCQCN, and veth has
no PFC).

## 2. RoCE v2 on the wire — not run

No RoCE packets crossed the fabric, so there is no RoCE pcap. Prepared for
the next attempt:

- `fabric/experiments/e3/bth_decode.py` (stdlib only) parses classic pcap
  through Ethernet, IPv4, UDP 4791, and BTH. It decodes the opcode, SE,
  PadCnt, TVer, P_Key, FECN/BECN, DestQP, AckReq, and PSN, plus the ICRC
  position (last 4 bytes of the UDP payload). It also summarizes UDP source
  ports per destination QP, and DSCP/ECN. Field masks are from
  `drivers/infiniband/sw/rxe/rxe_hdr.h`. Unit tests in
  `fabric/tests/test_bth_decode.py` use synthetic frames.
- `run.py wire` captures on both spines through the tap sidecars and runs
  `tshark -d udp.port==4791,infiniband` on the busiest spine. It also
  compares 1 vs `-q 4` QPs using leaf uplink TX deltas, the method from
  [E1](E1-ecmp-hash.md).
- Expected entropy, from source rather than measurement: rxe fixes one UDP
  source port per QP, `qp->src_port = RXE_ROCE_V2_SPORT + (hash_32(qp_num(qp), 14) & 0x3fff)`
  with `RXE_ROCE_V2_SPORT = 0xc000` (`rxe_qp.c:256`, `rxe.h:38`). One QP is
  therefore one 5-tuple and lands on one spine, like E1's single L4 flow.
  Spreading needs several QPs, which gives the same few-flows imbalance E1
  measured. rxe copies the GRH traffic class into IPv4 TOS
  (`rxe_net.c:248`, `iph->tos = tos` from `av->grh.traffic_class`), so
  `--tclass 104` should appear on the wire as DSCP 26, ECN 00 (Not-ECT).
  Not verified.

A quick attempt to see DSCP 26 at the spine taps with TCP (`iperf3 --tos
104`, `tcpdump -v` on spine1-tap/spine2-tap `eth1`) captured 0 packets. The
capture filter or timing was not debugged for lack of time; there is no
DSCP-on-the-fabric result.

## 3. QoS: INTENT-ONLY design, EMULATED host classification

Design, sources, and SONiC field mapping: [`../qos/README.md`](../qos/README.md).
Render: `fabric/build/example/sonic/<switch>/config_db.qos.json` and
`fabric/build/example/hosts/<host>-qos.sh`.

Host classification check, `python -m fabric.experiments.e3.run qos`: host1
`eth1`, `prio bands 3`, flower filters on `ip_tos` with mask `0xfc`. The
command for each row was
`iperf3 -c 10.210.0.10 -B 10.210.0.2 -t 2 --tos <TOS> --json`, and each
cell is the `tc -s -j class show dev eth1` packet delta:

| Traffic | TOS | Band 1:1 (CNP, TC6) | Band 1:2 (RoCE, TC3) | Band 1:3 (default, TC0) |
|---|---:|---:|---:|---:|
| unmarked | 0 | 0 | 0 | 220,662 |
| DSCP 26 | 104 | 0 | 221,835 | 14 |
| DSCP 48 | 192 | 208,937 | 0 | 16 |

Marked traffic lands in the intended band. The 14 and 16 packets in the
default band during marked runs are probably iperf3's unmarked control
connection; this was not separately verified.

This proves classification only. veth has no PFC, no switch buffers, and no
queue ECN marking. Linux `prio` bands are strict priority, so the intent's
DWRR 50/50 is not reproduced (this kernel has no `sch_ets`:
`CONFIG_NET_SCH_ETS` is absent from `/proc/config.gz`). ECN marking with
`tc` RED is later work.

## 4. Headroom (INTENT-ONLY arithmetic)

Run `make fabric-headroom`. The tool reproduces H3C's 100GE/100 m worked
example (27,592 B). With MTU_R 9216, MTU_S 4200, H3C's 3840 B response, and
5.2 ns/m propagation, headroom per port per priority is 17,646 B
(100G/3 m), 22,456 B (400G/10 m), and 121,256 B (800G/100 m). Using IEEE
802.3 31B pause quanta for the response, 400G/10 m rises to 76,536 B. On a
64 × 800G Spectrum-4 (128 MB shared buffer), the 100 m worst case reserves
5.8 % of the buffer with 1 lossless class, 11.6 % with 2, 23.1 % with 4, and
46.3 % with 8. That reserved memory is idle until PAUSE fires, and it comes
on top of the XOFF thresholds, so practical designs keep 1–2 lossless
classes.

## Failures diagnosed

1. **Image not pullable by the lab.** Symptom: `pinging container registry
   localhost:5000: ... http: server gave HTTP response to HTTPS client`.
   Evidence: setuid containerlab → system Podman; `oci-archive:` rejected
   (`only docker transport is supported`). Cause: root Podman requires TLS
   unless a registry is marked insecure. Fix: the user added
   `50-goodput-local.conf` for `localhost:5000` only.
2. **`IB device 'rxe_host1_a' wasn't found`** inside the host. Evidence:
   container `/dev/infiniband` had only `uverbs0`, while `/sys/class/infiniband_verbs`
   listed `uverbs1`–`uverbs8` (host `/dev/infiniband/uverbs3` = `231:195` =
   `rxe_host1_a`). Cause: the privileged container's `/dev` is populated at
   creation, before the rxe devices exist. Fix: the rendered host setup now
   `mknod`s missing `uverbsN` nodes from `/sys/class/infiniband_verbs/*/dev`.
3. **Verbs traffic fails (`Failed status 5`).** Evidence and cause: §0; rxe
   is bound to `init_net` in Linux 6.18. No fix in this lab.
4. **No `tcpdump` on spines.** The FRR image is Alpine without capture tools.
   Fix: `capture_taps` in intent renders `spineN-tap` nodes (the pinned host
   image, `network-mode: container:spineN`) instead of adding packages to the
   pinned FRR image.

## Notes for DESIGN §5 (for F2, who owns `fabric/DESIGN.md`)

- Soft-RoCE cannot be used inside containerlab host namespaces on this
  kernel. Linux 6.18 `rdma_rxe` routes (`rxe_net.c:37`) and receives
  (`rxe_net.c:633/648`) only in `init_net`. Any RDMA-on-fabric claim needs a
  kernel with rxe netns support, init-namespace endpoints, or real NICs.
- The lab runtime is rootful Podman through setuid containerlab. The host
  image comes from a localhost:5000 registry trusted by a root-owned
  `registries.conf.d` entry.
- RoCE v2 ECMP entropy in rxe is one UDP source port per QP
  (`rxe_qp.c:256`). Expect E1-style imbalance with few QPs; multi-QP
  collectives are the entropy lever.
- QoS intent: RoCE DSCP 26 → TC3 lossless (PFC 3); CNP DSCP 48 → TC6
  strict; default TC0. ECN Kmin/Kmax 150 KB/1.5 MB with Pmax 100 % (Cumulus
  5.16 defaults), below a 3 MB XOFF threshold (a design choice). PFC
  watchdog drop/200/200/200 ms (SONiC 202511 defaults). The validator
  enforces ECN < XOFF, a CNP class, and PFC on every lossless class.
- Headroom at 400G is 72.8 KB (3 m) and 76.4 KB (10 m) per port per
  priority, using the conservative IEEE response. Each lossless class
  reserves 5.8 % of a 128 MB buffer at 64 × 800G/100 m (H3C response term),
  so keep 1–2.
- The host Linux `prio` render shows DSCP classification only. Adding ECN
  (tc RED) and an ETS-capable kernel are prerequisites for any queueing
  experiment.
