# E7 — EVPN-VXLAN tenant VRFs on the front end

**Label: EMULATED.** FRR 10.2.1 BGP EVPN control plane, Linux VRF/VXLAN/bridge
data plane, veth links, kernel forwarding. Not a switch ASIC VTEP; tenant
throughput is Linux software encapsulation over veth.

## Concept

An AI cluster has separate networks ([DESIGN §1](../DESIGN.md#1-the-four-networks-of-an-ai-cluster)).
**The front-end network is where cloud multi-tenancy lives.** Customer VMs,
storage clients, and inference endpoints of different tenants share leaves and
spines, so the fabric needs per-tenant routing tables and an overlay.
**EVPN-VXLAN** provides it: a BGP control plane (`l2vpn evpn`) that distributes
MAC/IP and prefix reachability per tenant, over a VXLAN data plane between
VTEPs (leaf loopbacks).

**The backend RDMA rails stay in the default VRF.** They are isolated by rail
and pod partitioning (dedicated leaves/ports, scheduler-assigned jobs), not by
VXLAN. VXLAN adds 50 B per packet, puts a UDP/IP layer and a software or ASIC
lookup step in front of RoCE, and complicates ECN/PFC handling. The backend
rails in this lab do not change.

Mapping to L3VPN (MPLS VPN) terms:

| EVPN-VXLAN | L3VPN analogue | In this lab |
|---|---|---|
| Tenant VRF | VRF | `tenant-a` (table 1001), `tenant-b` (table 1002) |
| L3VNI (symmetric IRB) | VPN label identifying the VRF | 50001 / 50002, carried in the VXLAN header |
| Type-5 IP prefix route | VPNv4 prefix route | each tenant subnet, `advertise ipv4 unicast` |
| Type-2 MAC/IP route | (no direct analogue: host route + MAC) | endpoint /32 + MAC, imported into the VRF via the L3VNI RT |
| Route distinguisher | RD: makes overlapping prefixes unique | auto, `<router-id>:<n>` |
| Route target | RT: import/export policy | explicit per VNI and per VRF (below) |
| VTEP loopback | PE loopback / BGP next hop | leaf `10.200.0.1x/32`, already in the underlay |

## Design (intent `tenants:`)

[`../intent/fabric.yaml`](../intent/fabric.yaml) → `fabric/render/tenants.py`
(Linux) + `templates/frr/frr.conf.j2` (FRR). New range `10.220.0.0/16`. It
does not overlap the loopbacks (10.200/24), rails (10.210/16), management
(10.253/24), or the excluded 10.42/16, 10.43/16, 10.89.0.0/24; the validator
enforces this.

| Tenant | VRF table | L3VNI / RT | Segments (leaf: L2VNI, subnet, RT) | Endpoints |
|---|---|---|---|---|
| tenant-a | 1001 | 50001 / `65000:50001` | leaf1: 10101 10.220.11.0/24; leaf3: 10103 10.220.13.0/24 (RT `65000:<L2VNI>`) | ta1 (leaf1) 10.220.11.10, ta3 (leaf3) 10.220.13.10 |
| tenant-b | 1002 | 50002 / `65000:50002` | leaf1: 10201 10.220.21.0/24; leaf2: 10202 10.220.22.0/24; leaf4: 10204 10.220.24.0/24 | tb1 (leaf1), tb2 (leaf2), tb4 (leaf4), each .10 |

leaf1 hosts one endpoint of **each** tenant (ta1, tb1), so isolation is tested
on the same switch.

Choices and reasons:

- **One routed L2VNI/subnet per tenant per leaf, not a stretched subnet.**
  Every broadcast domain stays inside one leaf: no BUM flooding across the
  fabric, no ingress-replication lists, no cross-rack L2 failure domain. All
  cross-leaf tenant traffic is routed through the L3VNI (symmetric IRB),
  which is what is tested. A stretched subnet would also exercise type-3 IMET
  and bridged VXLAN; that is future work.
- **Anycast gateway.** Every tenant SVI on every leaf uses the same gateway
  MAC (`tenants.gateway_mac` 02:00:00:00:fe:01), and the gateway IP is
  always `.1` of the local subnet. With per-leaf subnets, the anycast *IP*
  only pays off when a subnet is later stretched; the MAC is uniform today.
- **Symmetric IRB.** Ingress leaf routes into the L3VNI and egress leaf routes
  out. Each leaf only needs its local L2VNIs plus the tenant's L3VNI. The L3VNI
  bridge has the VXLAN device as its only member and its SVI has no IP, per
  FRR's Linux interface guidance.
- **Explicit route targets (trap a).** Leaves are in different ASes
  (65101–65104). FRR's auto-derived RTs are `AS:VNI`, so leaf1 would export
  `65101:50001` while leaf3 imports `65103:50001`, and nothing would import.
  Options: explicit RTs in intent, or FRR's `autort rfc8365-compatible`.
  **Chosen: explicit `65000:<VNI>` in intent.** It is vendor-neutral: the
  same values render to NX-OS (`route-target both`) without relying on an
  FRR-specific auto-RT scheme. The validator checks uniqueness. The rt-auto
  drill below shows the failure mode.
- **Spines are transit only (trap b).** `l2vpn evpn` is activated on every
  spine session with `neighbor <peer> attribute-unchanged next-hop`. Spines
  have no VNIs or VRFs; they must keep the originating VTEP as next hop.
  FRR: "`neighbor <PEER> attribute-unchanged [{as-path|next-hop|med}]`:
  specifies attributes to be left unchanged for advertisements sent to a peer"
  (FRR 10.2 BGP, *Configuring Peers*).
- **MTU (trap c).** The containerlab veth MTU is **9500**, not 1500 (measured:
  `ip link show eth1` on leaf1 → `mtu 9500`). Intent makes it explicit:
  `fabric_mtu: 9500`, rendered on every link. Tenant MTU is 9000 on VXLAN
  devices, bridges, leaf tenant ports and endpoints. The validator rejects
  `tenants.mtu + 50 > fabric_mtu`: outer Ethernet 14 + IPv4 20 + UDP 8 +
  VXLAN 8 = 50 B ([RFC 7348 §5](https://www.rfc-editor.org/rfc/rfc7348#section-5)).
- **VTEP source = loopback (trap d).** `ip link add vxN type vxlan id N local
  <leaf loopback> dstport 4789 nolearning`. The loopbacks are already
  advertised in the underlay; tests assert reachability and two ECMP paths.

Rendered FRR (leaf1 excerpt, from `fabric/build/example/frr/leaf1/frr.conf`;
the order matters, see "Traps that actually bit"):

```text
vrf tenant-a
 vni 50001
exit-vrf
...
router bgp 65101 vrf tenant-a          ! VRF instances before the default instance
 bgp router-id 10.200.0.11
 address-family ipv4 unicast
  redistribute connected
 address-family l2vpn evpn
  advertise ipv4 unicast               ! type-5
  route-target import 65000:50001
  route-target export 65000:50001
router bgp 65101
 ...
 address-family l2vpn evpn
  neighbor FABRIC activate
  neighbor FABRIC route-map FABRIC-IN in
  neighbor FABRIC route-map FABRIC-OUT out
  advertise-all-vni
  vni 10101
   route-target import 65000:10101
   route-target export 65000:10101
  exit-vni
```

Spines: `address-family l2vpn evpn` → `neighbor PEER_LEAFx activate`, the
same route-maps, `neighbor PEER_LEAFx attribute-unchanged next-hop`. The
Linux side is `fabric/build/example/tenants/<leaf>-tenant-{devices,ports}.sh`.
The devices stage runs as the container command before FRR starts
(`sh tenant-devices.sh && exec /usr/lib/frr/docker-start`). The ports stage
runs as a containerlab exec once the veths exist, and checks that each
L3VNI carries its intent RT.

Sources:
- FRR 10.2 EVPN, *Linux Interface Configuration* (VRF + L3VNI bridge, "An
  L3-SVI should not be assigned an IP address", "Dynamic MAC/VTEP learning
  should be disabled", "local VTEP-IP should always be set to a reachable IP
  on the lo device") and *FRR Configuration* (`advertise-all-vni`,
  `vrf … vni`, `advertise ipv4 unicast` → type-5):
  <https://docs.frrouting.org/en/stable-10.2/evpn.html>.
- FRR 10.2 BGP, *Configuring Peers* (`attribute-unchanged`), *EVPN L3
  Route-Targets* (`route-target <import|export|both> <RTLIST|auto>`), *Enabling
  EVPN* (`advertise-all-vni` under `address-family l2vpn evpn`):
  <https://docs.frrouting.org/en/stable-10.2/bgp.html>.
- Linux `ip-link(8)` `vxlan` / `vrf` types:
  <https://man7.org/linux/man-pages/man8/ip-link.8.html>; kernel VRF
  documentation: <https://docs.kernel.org/networking/vrf.html>.
- eBGP EVPN with different ASes makes auto `AS:VNI` RTs mismatch (NVIDIA
  Cumulus Linux, *EVPN Enhancements*, "Route Targets"):
  <https://docs.nvidia.com/networking-ethernet-software/cumulus-linux-59/Network-Virtualization/Ethernet-Virtual-Private-Network-EVPN/EVPN-Enhancements/>.
- Tenant endpoint image: `docker.io/nicolaka/netshoot:v0.13@sha256:5a21d467…02fb8`
  (the pin F1 used for hosts).

## Predictions (written before deployment)

| Check | Prediction |
|---|---|
| `show evpn vni` on leaf1 | 4 VNIs: 10101 and 10201 L2, 50001 and 50002 L3, each with the leaf1 VTEP 10.200.0.11 |
| Type-2 routes | one MAC/IP route per endpoint (5), each carrying L2VNI RT + L3VNI RT + router-MAC; remote leaves install them as /32s in the VRF |
| Type-5 routes | one per tenant segment (5 prefixes), next hop = originating leaf loopback on every leaf **and** on the spines |
| ta1 ↔ ta3, tb1 ↔ tb2 ↔ tb4 | ping and iperf3 succeed; iperf3 limited by the shaped uplinks if shaping is on, otherwise by CPU (several Gbit/s) |
| ta1 ↔ tb1 (same leaf), any a ↔ b | ping fails: different VRFs, no leaking |
| tenant → backend rail | fails: tenant VRFs have no 10.210/16 route; the default VRF has no 10.220/16 route |
| backend rails, VMs | unaffected; original 44 fabric-test checks still pass |
| Spine-tap pcap | UDP 4789 with VNI 50001 for tenant-a and 50002 for tenant-b (routed via L3VNI), outer IPs = leaf loopbacks |
| `ping -M do -s 8972` / `-s 8973` | 8972 (9000 B packet) passes; 8973 fails locally ("message too long", MTU 9000) |
| rt-auto drill (leaf3 drops explicit import RT) | leaf3 falls back to auto `65103:50001`; imports nothing from other leaves; ta1 ↔ ta3 fails; restore fixes it |
| nh-rewrite drill (spines drop `attribute-unchanged next-hop`) | Uncertain. Either FRR keeps the EVPN next hop for eBGP anyway, or it rewrites to the spine and breaks VXLAN; to be measured |
| Trap (c) | Avoided by validation (9000 + 50 ≤ 9500) |

## Results

Run on 2026-10-16 after `make fabric-up` (deploy from this branch, 19 nodes),
with shaping **off**: `python -m fabric.experiments.e7_evpn all`, then `drills`.
Raw outputs of every command are in [`e7-results.json`](e7-results.json); the pcaps
are [`e7/vxlan-spine1.pcap`](e7/vxlan-spine1.pcap) (3,424 B) and
[`e7/vxlan-spine2.pcap`](e7/vxlan-spine2.pcap) (6,824 B). **EMULATED.**

### Prediction vs measured

| Check | Prediction | Measured |
|---|---|---|
| `show evpn vni` (leaf1) | 10101/10201 L2, 50001/50002 L3, correct VRFs | `10201 L2 tenant-b`, `10101 L2 tenant-a`, `50002 L3 tenant-b`, `50001 L3 tenant-a` (after the fixes below) |
| Type-2 | one MAC/IP per endpoint with L2 RT + L3 RT + RMAC | e.g. `[2]:[0]:[48]:[aa:c1:ab:c7:aa:1c]:[32]:[10.220.11.10]  RT:65000:10101 RT:65000:50001 ET:8 Rmac:82:b5:4f:04:75:67`; remote leaves install it as a /32 (`10.220.11.10 nhid 37 via 10.200.0.11 dev br50001 … onlink` in leaf3's tenant-a table) |
| Type-5 | 5 prefixes, next hop = originating VTEP on leaves and spines | spine1: 5 prefixes, e.g. `[5]:[0]:[24]:[10.220.22.0]  10.200.0.12 … 65102 ?  RT:65000:50002`; on leaf3 every type-5 next hop is the originating loopback (10.200.0.11/.12/.13/.14), ECMP via both spines |
| `show bgp vrf tenant-a ipv4` (leaf1) | local + remote subnet + host route | `10.220.11.0/24 0.0.0.0`, `10.220.13.0/24 10.200.0.13<` ×2, `10.220.13.10/32 10.200.0.13<` ×2 |
| `bridge fdb` (leaf1 vx50001) | remote router MAC at remote VTEP | `5e:e5:3f:b2:e8:f9 dst 10.200.0.13 self extern_learn` (leaf3's RMAC) |
| Same-tenant reachability | ping works | 8/8 same-tenant pairs reached (ta1↔ta3, tb1↔tb2↔tb4) |
| Cross-tenant, incl. ta1↔tb1 on leaf1 | fails | 12/12 cross-tenant attempts failed |
| Tenant → backend rail | fails | 15/15 failed; leaf1 default VRF has no 10.220/16 route (`ip route show 10.220.0.0/16` empty) |
| iperf3 | works; CPU-bound unshaped | ta1→ta3 5.62 Gbit/s, tb1→tb4 5.58 Gbit/s, 0 retransmits (3 s, unshaped; Linux VXLAN in software, **not** VTEP ASIC throughput) |
| Spine-tap pcap | VNI 50001 tenant-a, 50002 tenant-b, outer = loopbacks | spine1: `VNI 50001 10.200.0.11->10.200.0.13 inner 10.220.11.10->10.220.13.10` ×10, `VNI 50002 10.200.0.14->10.200.0.12 inner 10.220.24.10->10.220.22.10` ×10; spine2 shows the other directions/paths. Tenant traffic crosses the fabric on the L3VNI, never the L2VNI |
| MTU 9000 / 9001 | 8972 passes; 8973 refused | `-M do -s 8972` 2/2 replies (`8980 bytes from …`); `-s 8973` → `local error: message too long, mtu=9000` |
| Backend rails + VMs | unaffected | `make fabric-test`: 61 passed (the 44 original checks + shaping, exporter, and 10 tenant checks) |

### Trap drills (runtime change, then restore; every drill restored and re-verified)

| Trap | Drill | Prediction | Measured |
|---|---|---|---|
| (a) RT, import side | leaf3 tenant-a: `no route-target import 65000:50001` | import falls back to auto `65103:50001` → leaf3 imports nothing → ping fails | Import RT became `65103:50001`, **but ping kept working**, even after `clear bgp l2vpn evpn * soft in`. FRR's auto import matches `*:VNI` under eBGP (the Cumulus/NVIDIA behavior cited above), so the AS part is ignored. **Prediction wrong.** |
| (a) RT, export side | leaf3 tenant-a: `no route-target export 65000:50001` | leaf1 (explicit import 65000:50001) drops leaf3's routes | leaf3 exported `RT:65103:50001`; leaf1 received the type-5 (`[5]:[0]:[24]:[10.220.13.0] … RT:65103:50001`) but did not import it. leaf1's tenant-a table held only its local subnet; ta1→ta3 failed; restore fixed it. This is the mixed-vendor or mixed-config case: explicit RTs on one side, auto on the other |
| (b) next hop | spines: `no neighbor PEER_LEAFx attribute-unchanged next-hop` + soft out | uncertain | **FRR rewrites the EVPN next hop to the spine.** leaf3's type-5 next hops changed from the VTEP loopbacks to `10.200.0.1` / `10.200.0.2`; tenant routes became `nexthop via 10.200.0.1 dev br50001 … via 10.200.0.2`. The spines are not VTEPs, so ta1→ta3 failed. Restore → next hops back to the VTEPs, ping OK |
| (c) MTU | ta1/ta3 + leaf1/leaf3 tenant devices raised to 9500 (= fabric MTU) | 9500 + 50 > 9500 → loss | **Linux's VXLAN does PMTU itself**: `ping -M do -s 9472` → `Frag needed and DF set (mtu = 9450)` (9500 − 50); no fragments (`IpFragCreates 0`). The 9000-B packet appeared on the spine tap as `length 9050 … VXLAN … vni 50001`, the 50 B overhead directly. A hardware VTEP usually drops oversize encapsulated frames silently; the lab's software VTEP is more forgiving than a switch would be |
| (d) VTEP source | not drilled | — | `vx10101 … vxlan id 10101 local 10.200.0.11`; loopbacks are in the underlay with 2 ECMP paths (fabric-test) |

### Traps that actually bit during bring-up (failures diagnosed)

1. **`(Policy)` on every EVPN session.** Symptom: `show bgp l2vpn evpn
   summary` showed `(Policy) (Policy)` and no prefixes. Evidence: the
   `FABRIC-IN/OUT` route-maps were only applied in the IPv4 unicast address
   family. Cause: eBGP requires an explicit policy per address family
   (RFC 8212 behavior; `frr defaults traditional` did not disable it on 10.2.1).
   Fix: render `neighbor <group> route-map FABRIC-IN in` / `FABRIC-OUT out`
   inside `address-family l2vpn evpn` too.
2. **L3VNI bound to the default VRF.** Symptom: `50001 L2 … tenant-a`,
   `50002 L3 … default`; running config showed a global `vni 50002` and
   `vrf tenant-a` with no `vni`. Evidence: applying
   `vrf tenant-a / vni 50001` interactively worked. Cause: the `vrf … vni`
   stanzas came *after* `router bgp` in frr.conf, so the file parser executed
   ` vni N` at global config level. Fix: render `vrf … vni` stanzas before any
   `router bgp` (FRR's own running-config order). Creating the VRF devices
   before FRR starts (container `cmd` wrapper) was done first and did not fix
   this; it is kept because it matches a real NOS boot order.
3. **Phantom L3VNI instance with auto RTs on leaf2 (trap a, live).** Symptom:
   tenant-b to/from tb2 failed; leaf2's L3VNI showed `RD 0.0.0.0:3`,
   `65102:50002` (auto). `show bgp l2vpn evpn vni` listed **two** L3 entries for
   50002, and `no router bgp 65102 vrf tenant-b` was refused ("Please
   unconfigure l3vni"). Cause: `advertise-all-vni` in the default instance
   made bgpd process the L3VNI before the `router bgp … vrf` block (later in
   the file) existed, so bgpd auto-created a VRF instance with router-id 0 and
   AS:VNI RTs. A zebra-side rebind (`no vni` / `vni`) fixed forwarding but
   left the phantom entry. Fix: render the `router bgp <asn> vrf <tenant>`
   blocks **before** the default instance. Two consecutive fresh deploys then
   showed exactly one entry per VNI with the intent RTs on every leaf.
   `test_every_vni_uses_the_intent_route_targets` now fails on duplicates
   or auto RTs, and the leaf exec stage fails if an L3VNI lacks its RT.
4. **Killed a leaf while debugging.** `frrinit.sh restart` inside the FRR
   container killed the container's main process (watchfrr under tini). Lab
   recovery was a redeploy; never restart FRR that way in this image.
