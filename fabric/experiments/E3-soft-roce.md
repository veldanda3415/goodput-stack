# E3 — Soft-RoCE across the fabric and lossless RoCE QoS

**Status (2026-10-16):** Task 1 is complete: two VM endpoints run
**SOFT-ROCE** in separate guest kernels across the **EMULATED** fabric and
complete RC verbs traffic across a spine. Task 2 wire decode is complete.
Linux 6.18's initial-netns limitation still blocks the original container
hosts, but VM endpoints provide a working path for issue #31's experiment.

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
| Verbs traffic in container hosts | `ib_write_bw -d rxe_host1_a -x 1 -s 65536 -n 100 -F --bind_source_ip 10.210.0.2 10.210.0.6` (server on host2: `ib_write_bw -d rxe_host2_a -x 1 -s 65536 -n 100 -F`) | **failed**: `Completion with error at client` / `Failed status 5: wr_id 0 syndrom 0x0` / `scnt=100, ccnt=0` |

GID index choice: rxe derives GIDs from the addresses of its netdev. The RoCE
v2 GID for a rail is the IPv4-mapped address `::ffff:<rail IPv4>`, and it is
index 1 on all eight devices (`fabric/experiments/e3-results.json`,
`devices`). The driver selects it by matching that address and type `RoCE v2`
in `ibv_devinfo -v`; it does not hard-code the index.

### Why verbs traffic fails in containers: rxe is bound to the initial network namespace

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
rootful, is already in use. This feasibility result still applies to the
original container hosts; the VM endpoint path below completes the requested
RDMA experiment without changing that kernel limitation.

The VM endpoint path now avoids that limitation by running `rdma_rxe` in each
guest's init network namespace. The VM runner bridges its containerlab rail
port to a QEMU TAP device; the QEMU guest owns the IPv4 rail address and rxe
device. This is still software RoCE over emulated veth links, not NIC
performance.

### VM endpoint pin and prediction

Two QEMU guests use 768 MiB RAM and 2 vCPUs each. `/dev/kvm` is available and
the runner selects KVM when readable/writable, otherwise QEMU TCG. The guest
image is the Debian 13 generic amd64 cloud image with SHA-512
`d4721b56d60472370f3ff088a85ca36f298b360d3131af421a009bb8ea03c4d80eb67915bb57a69f6057e56c5bd48e69d3a47fbc5b8efacc5434a9c756b345d3`.
The pinned runner image is `localhost:5000/goodput-roce-vm:0.1.0@sha256:8b2c5ba8936c2d21dc657fe6b268857490360a5e6a3fa8e6172aeecce53b88f7`.

**Prediction before the cross-spine measurements:** SOFT-ROCE verbs should
complete because rxe packet routing and UDP 4791 now belong to each guest's
init namespace. Its CPU-bound software datapath should be much slower than
the guest-to-guest iperf3 TCP datapath; 1 MiB messages should give higher
bandwidth than 64 KiB, while `ib_read_lat` should report sub-millisecond
software latency on an unloaded lab. These are predictions, not results.

| Path / test | Prediction | Measured result |
|---|---|---|
| vmhost1 rail A → vmhost2 rail A, `ib_write_bw`, 64 KiB / 1 MiB, 3 repeats | QP should establish; CPU-bound and below iperf3 | 64 KiB: 0.64 Gbit/s (0.61–0.68); 1 MiB: 0.60 Gbit/s (0.57–0.62) |
| Same path, `ib_read_lat`, 64 KiB / 1 MiB, 3 repeats | RC read completes; software latency, not NIC latency | 64 KiB: 1,301.77 µs (1,199.97–1,349.30); 1 MiB: 10,940.61 µs (10,780.51–11,224.85) |
| Same path, iperf3 TCP, 64 KiB / 1 MiB, 3 repeats | higher throughput than Soft-RoCE | 64 KiB: 2.627 Gbit/s (2.186–2.718); 1 MiB: 2.541 Gbit/s (2.465–2.558) |

Verbs client CPU was 54.24% / 55.80% for 64 KiB / 1 MiB; `mpstat %usr`
median was 29.62% / 28.90%. iperf3 median sender/receiver CPU was
8.98%/49.44% and 12.45%/44.99%, respectively. Measured command lines and
raw outputs are recorded in [`e3-results.json`](./e3-results.json).

Possible ways forward for the original container hosts:

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
| VM runner | `localhost:5000/goodput-roce-vm:0.1.0@sha256:8b2c5ba8936c2d21dc657fe6b268857490360a5e6a3fa8e6172aeecce53b88f7` | Digest of the pushed runner image; image build and QEMU/TAP wiring are in `fabric/images/roce-vm/Containerfile` and `vmhost-start.sh` |
| VM guest image | Debian 13 generic amd64 qcow2; SHA-512 `d4721b56d60472370f3ff088a85ca36f298b360d3131af421a009bb8ea03c4d80eb67915bb57a69f6057e56c5bd48e69d3a47fbc5b8efacc5434a9c756b345d3` | <https://cloud.debian.org/images/cloud/> index; exact content is verified in the runner build |
| VM runner base and QEMU packages | Debian `trixie-20260918-slim@sha256:7792b1f7702a86946cd518db72b6a407302c3e9bc1635634368b878189e8221c`; QEMU `1:10.0.13+ds-0+deb13u1`; cloud-image-utils `0.33-1`; iproute2 `6.15.0-1`; openssh-client `1:10.0p1-7+deb13u4` | `fabric/images/roce-vm/Containerfile`; packages installed from <https://snapshot.debian.org/> at `20260918T000000Z` |
| VM guest packages | rdma-core/ibverbs `56.1-1`; perftest `25.01.0+0.80-1`; iperf3 `3.18-2+deb13u2`; tcpdump `4.99.5-2`; tshark `4.4.18-0+deb13u1`; sysstat `12.7.5-2`; iproute2 `6.15.0-1`; remaining utilities and OpenSSH pinned in `VM_RDMA_PACKAGES` | `fabric/render/render.py`; package versions resolved from <https://snapshot.debian.org/> at `20260918T000000Z` |
| Local registry | `docker.io/library/registry:3.1.1@sha256:3d527cee870ddd0fc8a31f99b2fdfb6451801a8dd4f5a92c1ec36dae24c14274` | Docker Hub `library/registry`; release before `3.1.2` |
| Root Podman trust | `/etc/containers/registries.conf.d/50-goodput-local.conf`: `[[registry]] location = "localhost:5000" insecure = true` | Created by the user with sudo; containerlab 0.78.2 accepts only `docker://` references (`Unsupported transport oci-archive ... only docker transport is supported`) |

The runner uses a containerlab `kind: linux` node and generated topology
links (containerlab [Topology definition: Nodes and Links](https://containerlab.dev/manual/topo-def-file/)).
Its rail-facing TAP is bridged to the node's `eth1`; the QEMU guest's virtio
NIC owns the rail MAC/IP (QEMU [Network emulation: TAP and user-mode
backends](https://www.qemu.org/docs/master/system/devices/net.html#using-tap-network-interfaces)).
QEMU's user-mode NIC is only for SSH/guest package bootstrap. `/dev/kvm` was
readable and writable in both runners, so both guests used KVM (not TCG).
Each guest is configured for 768 MiB and 2 vCPUs. `make fabric-up` took
18.03 s (`/usr/bin/time -f 'fabric-up elapsed_seconds=%e' make fabric-up`);
the subsequent `make fabric-test` reported **32 passed**.

## 1. RDMA across the fabric — complete (SOFT-ROCE + EMULATED)

**Prediction before the measurement:** the guest init namespaces should let
the RC QPs send and receive. Because rxe is CPU-bound, verbs throughput
should be lower than guest-to-guest iperf3; 1 MiB read latency might approach
the millisecond scale or higher. The earlier expectation of sub-millisecond
latency was wrong, especially at 1 MiB.

Command: `./.venv/bin/python -m fabric.experiments.e3.run rdma --path vm-cross-spine`.
The driver ran three repeats per cell on vmhost1 rail A (`10.210.0.18`) to
vmhost2 rail A (`10.210.0.22`), recorded the client/server command lines and
raw outputs in [`e3-results.json`](./e3-results.json), and sampled guest CPU
with `mpstat`. `ibv_devinfo -v` reported the RoCE v2 IPv4-mapped GID
`::ffff:10.210.0.18` at index 1 on vmhost1 and
`::ffff:10.210.0.22` at index 1 on vmhost2. `rdma link show` reported both
devices `ACTIVE`, and traceroute crossed vmhost1's leaf, spine1, and
vmhost2's leaf.

| Path/test | Prediction | Measured result (median, range; 3 repeats) |
|---|---|---|
| `ib_write_bw`, 64 KiB | Completes; below TCP | 0.64 Gbit/s (0.61–0.68); perftest client CPU 54.24%, `mpstat %usr` 29.62% median |
| `ib_write_bw`, 1 MiB | Completes; below TCP | 0.60 Gbit/s (0.57–0.62); perftest client CPU 55.80%, `mpstat %usr` 28.90% median |
| `ib_read_lat`, 64 KiB | RC read completes; predicted sub-ms | 1,301.77 µs (1,199.97–1,349.30); prediction missed |
| `ib_read_lat`, 1 MiB | RC read completes; software latency | 10,940.61 µs (10,780.51–11,224.85) |
| iperf3 TCP, 64 KiB | Faster than verbs | 2.627 Gbit/s (2.186–2.718); median sender/receiver CPU 8.98%/49.44% |
| iperf3 TCP, 1 MiB | Faster than verbs | 2.541 Gbit/s (2.465–2.558); median sender/receiver CPU 12.45%/44.99% |

`rdma statistic show link <device>/1` was sampled immediately before and
after the workload. vmhost1 changed from 0/0 to `sent_pkts=1,442,515`,
`rcvd_pkts=3,286,439`; vmhost2 changed from 0/0 to
`sent_pkts=3,286,439`, `rcvd_pkts=1,442,236`. Counters prove packets moved;
the 279-packet difference in the forward direction is not explained by this
measurement, so this is not evidence of loss-free delivery. The command and
raw counter output are in the result JSON.

The exact 64 KiB write client command was
`ib_write_bw -d rxe_vmhost1_a -x 1 -s 65536 -D 3 --report_gbits -F --cpu_util --bind_source_ip 10.210.0.18 10.210.0.22`;
server command:
`timeout 40 ib_write_bw -d rxe_vmhost2_a -x 1 -s 65536 -D 3 --report_gbits -F`.
The corresponding iperf3 client command was
`iperf3 -c 10.210.0.22 -B 10.210.0.18 -t 3 -l 65536 --json`; sizes and
commands for all six cells and 18 repeated runs are preserved in the JSON.

This proves the verbs API, RC QP/MR setup, and RoCE v2 traffic routed as
ordinary UDP/IP over the BGP fabric. It does **not** prove NIC throughput,
latency, losslessness, or congestion control (rxe has no DCQCN, and veth has
no PFC). These are **SOFT-ROCE** results on an **EMULATED** fabric, not NIC
performance.

## 2. RoCE v2 on the wire — complete (SOFT-ROCE + EMULATED)

**Prediction before the wire experiment:** one QP has one UDP source port
and should use one source-leaf uplink. Four and sixteen QPs add flow hashes
and might spread, but E1 found few-flow hash splits lumpy. With
`fib_multipath_hash_policy=0` (L3), I expected same-IP RoCE flows to remain
on one spine despite their distinct UDP ports. `--tclass 104` should produce
DSCP 26 / Not-ECT (ECN bits 00); the VM guest tc egress classifier should
count the traffic in band `1:2`. A correctly bound `iperf3 --tos 104`
captured concurrently on both spine links should reveal whether the earlier
zero-packet TCP attempt was a capture setup problem.

Command: `./.venv/bin/python -m fabric.experiments.e3.run wire`. Three
repeats per QP count completed. The driver used the generated rail-facing
links, logged each tcpdump command/status, source UDP port per destination
QP, uplink TX deltas and guest tc counters. There were **1,185,800 bytes**
of pcap artifacts across the 22 saved files, under the 2 MiB cap; full files
and decoded excerpts are in `fabric/experiments/e3/` and
[`e3-results.json`](./e3-results.json).

| Experiment | Prediction | Measured result |
|---|---|---|
| 1 QP × 3 | One source port, one spine | 1 distinct UDP source port per run; every observed QP landed on spine2 |
| 4 QPs × 3 | 4 source ports; L3 hash keeps same IP pair together | 4 distinct ports/run; all 4 QPs landed on spine2 in every repeat |
| 16 QPs × 3 | 16 ports; likely same spine with L3 hash | 16 distinct ports/run (extended capture); every QP landed on spine2 in all 3 repeats |
| RoCE DSCP sample | DSCP 26 / Not-ECT; class `1:2` | 200/200 decoded UDP 4791 packets were DSCP 26 / Not-ECT; tc delta `1:2=236,544`, default `1:3=21` |
| TCP `--tos 104` control | Capture on one active spine with DSCP 26 | 100 packets captured on spine2: 84 DSCP 26 / Not-ECT and 16 DSCP 0 / Not-ECT; tc delta `1:2=685,433`, default `1:3=16`; received 2.636 Gbit/s |

The leaf1 link TX byte deltas (eth1 → spine1, eth2 → spine2) were:

| QPs | Repeat 1 (bytes) | Repeat 2 (bytes) | Repeat 3 (bytes) |
|---:|---|---|---|
| 1 | 10,818 / 266,194,648 | 10,904 / 262,315,950 | 10,799 / 263,285,283 |
| 4 | 10,713 / 333,455,401 | 10,799 / 335,048,481 | 10,904 / 328,053,008 |
| 16 | 11,076 / 372,884,254 | 11,068 / 403,221,687 | 11,057 / 385,143,791 |

All RoCE captures observed data only at spine2; the small eth1 byte deltas
are leaf TX totals, not matching UDP 4791 frames. Leaf1 reported
`net.ipv4.fib_multipath_hash_policy=0`, so the kernel uses the L3 hash: all
QPs share the same IP pair and do not use their distinct UDP source ports
for ECMP selection. This matches the L3 prediction and E1's low-entropy
result. Exact UDP source ports and each QP/port/spine mapping are retained in
the result JSON.

The full DSCP sample pcap (`tclass104-1qp-spine2.pcap`) decoded 200 BTHs:
4 RC RDMA WRITE First, 191 Middle, 3 Last, and 2 RC Acknowledge; DestQP
`0x000112`, PSNs 9,779,518–9,779,715, 197 `AckReq=0` and 3 `AckReq=1`,
FECN/BECN both clear. The first packet's captured ICRC was `733da022`.
Wireshark/TShark 4.4.18 reported DSCP 26, ECN 0, UDP sport 58688, BTH
opcode 6, DestQP `0x000112`, PSN 9779518, AckReq false, and ICRC
`0x733da022`. The standalone decoder command was
`./.venv/bin/python fabric/experiments/e3/bth_decode.py fabric/experiments/e3/tclass104-1qp-spine2.pcap --limit 4`.

The prior quick TCP capture's exact command/filter was not retained, so its
specific zero-packet cause cannot be proven. A controlled reproduction with
source-bound iperf3 and a concurrent `tcpdump ... tcp and host 10.210.0.18
and host 10.210.0.22` captured 100 frames, demonstrating the expected spine
path and DSCP marking. During debugging, the E3 driver itself reproduced a
separate stale-pcap failure: tcpdump refused a reused file path with
`Permission denied`; unique remote filenames and checked return/status
output fixed the harness. See Failure 7.

Prepared for this task:

- `fabric/experiments/e3/bth_decode.py` (stdlib only) parses classic pcap
  through Ethernet, IPv4, UDP 4791, and BTH. It decodes the opcode, SE,
  PadCnt, TVer, P_Key, FECN/BECN, DestQP, AckReq, and PSN, plus the ICRC
  position (last 4 bytes of the UDP payload). It also summarizes UDP source
  ports per destination QP, and DSCP/ECN. Field masks are from
  `drivers/infiniband/sw/rxe/rxe_hdr.h`. Unit tests in
  `fabric/tests/test_bth_decode.py` use synthetic frames.
- `run.py wire` captures on both spines through the tap sidecars and runs
  `tshark -d udp.port==4791,infiniband` on the busiest spine. It also
  compares 1 vs `-q 4` vs `-q 16` QPs using leaf uplink TX deltas, the method from
  [E1](E1-ecmp-hash.md).
- Expected entropy, from source rather than measurement: rxe fixes one UDP
  source port per QP, `qp->src_port = RXE_ROCE_V2_SPORT + (hash_32(qp_num(qp), 14) & 0x3fff)`
  with `RXE_ROCE_V2_SPORT = 0xc000` (`rxe_qp.c:256`, `rxe.h:38`). One QP is
  therefore one 5-tuple and lands on one spine, like E1's single L4 flow.
  Spreading needs several QPs, which gives the same few-flows imbalance E1
  measured. rxe copies the GRH traffic class into IPv4 TOS
  (`rxe_net.c:248`, `iph->tos = tos` from `av->grh.traffic_class`), so
  `--tclass 104` appears on the wire as DSCP 26, ECN 00 (Not-ECT), as
  confirmed by the 200-packet TShark/decoder sample above.

A quick pre-VM attempt to see DSCP 26 at the spine taps with TCP
(`iperf3 --tos 104`, `tcpdump -v` on spine1-tap/spine2-tap `eth1`) captured 0
packets. Its capture filter/timing was not debugged; there is no DSCP-on-wire
result from that attempt.

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

This proves host classification only. veth has no PFC or switch buffers.
Linux `prio` bands are strict priority, so the intent's DWRR 50/50 is not
reproduced (this kernel has no `sch_ets`: `CONFIG_NET_SCH_ETS` is absent from
`/proc/config.gz`). The separate **EMULATED** `tc` RED/ECN experiment and
its TCP/SOFT-ROCE results are in [E4](E4-ecn.md).

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
3. **Verbs traffic fails in original container hosts (`Failed status 5`).**
   Evidence and cause: §0; rxe is bound to `init_net` in Linux 6.18. Separate
   QEMU guest kernels resolve this for VM endpoints; container-host endpoints
   remain blocked.
4. **No `tcpdump` on spines.** The FRR image is Alpine without capture tools.
   Fix: `capture_taps` in intent renders `spineN-tap` nodes (the pinned host
   image, `network-mode: container:spineN`) instead of adding packages to the
   pinned FRR image.
5. **VM guest cloud-init did not configure its fabric NIC.** Symptom:
   cloud-init status `error`, no rxe link. Evidence: cloud-init v1 rejects
   `set-name`; the guest NIC names were `management` and `fabric`, while the
   generated `runcmd` used `fabric0`. Fix: omit `set-name` in network-config
   and use `fabric` consistently; `vm-exec` now surfaces cloud-init failures.
6. **VM guest could not ping its leaf or a remote VM after cloud-init passed.**
   Evidence: runner `ip -d link show br-fabric` reported the bridge `state
   DOWN`; bringing it up immediately made the gateway and cross-spine pings
   succeed. Fix: explicitly `ip link set br-fabric up` before QEMU starts.
7. **Repeated E3 captures reported zero packets or reused an older pcap.**
   Evidence: `tcpdump` reported `Permission denied` on the same `/tmp/*.pcap`
   path, while the driver ignored the nested exit status and read that old
   file. Fix: use a unique per-run remote path, retain and check tcpdump's
   exit/status output, and remove that exact temporary file after transfer.

## Notes for DESIGN §§5–6

- Linux 6.18 `rdma_rxe` in container host namespaces routes
  (`rxe_net.c:37`) and receives (`rxe_net.c:633/648`) only in `init_net`.
  QEMU guest kernels provide working **SOFT-ROCE** endpoints, but all
  measurements remain software over **EMULATED** veth links, not NIC
  performance.
- The lab runtime is rootful Podman through setuid containerlab. The host
  image comes from a localhost:5000 registry trusted by a root-owned
  `registries.conf.d` entry.
- RoCE v2 ECMP entropy in rxe is one UDP source port per QP
  (`rxe_qp.c:256`). E3 confirms that L3 still pins all same-IP-pair QPs to
  spine2; E5 measures L4 distribution over both emulated spines.
- QoS intent: RoCE DSCP 26 → TC3 lossless (PFC 3); CNP DSCP 48 → TC6
  strict; default TC0. ECN Kmin/Kmax 150 KB/1.5 MB with Pmax 100 % (Cumulus
  5.16 defaults), below a 3 MB XOFF threshold (a design choice). PFC
  watchdog drop/200/200/200 ms (SONiC 202511 defaults). The validator
  enforces ECN < XOFF, a CNP class, and PFC on every lossless class.
- Headroom at 400G is 72.8 KB (3 m) and 76.4 KB (10 m) per port per
  priority, using the conservative IEEE response. Each lossless class
  reserves 5.8 % of a 128 MB buffer at 64 × 800G/100 m (H3C response term),
  so keep 1–2.
- Host `tc` proves DSCP classification only. E4's RED bottleneck is an
  explicit **EMULATED** qdisc experiment; it does not represent PFC, switch
  buffers or DCQCN. Linux `prio` is strict priority, not the intent's DWRR.
