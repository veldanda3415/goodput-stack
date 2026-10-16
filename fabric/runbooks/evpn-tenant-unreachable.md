# EVPN tenant can't reach its peer

**Label: MEASURED-IN-LAB (EMULATED, FRR 10.2.1 + Linux VXLAN)**: every cause
below was reproduced as a drill or hit during bring-up in
[E7](../experiments/E7-evpn-tenancy.md). Evidence: [`e7-results.json`](../experiments/e7-results.json).

## Symptom

Endpoint ping/iperf3 between two endpoints of the *same* tenant on different
leaves fails or loses large packets, while the backend rails and other
tenants are fine.

## Signals (in diagnostic order)

| Check | Command | Healthy (lab) | Fault seen in E7 |
|---|---|---|---|
| VNI ↔ VRF binding | `vtysh -c 'show evpn vni'` | `50001 L3 … tenant-a`, `10101 L2 … tenant-a` | `50002 L3 … default` / `50001 L2`: `vrf … vni` stanza parsed at the wrong level |
| One BGP L3VNI entry with the intent RT | `vtysh -c 'show bgp l2vpn evpn vni'` | one row per VNI, `65000:<VNI>` | two rows for 50002; `RD 0.0.0.0:3`, `65102:50002` (auto RT, phantom instance) |
| EVPN sessions carry routes | `vtysh -c 'show bgp l2vpn evpn summary'` | PfxRcd > 0 | `(Policy) (Policy)`: no route-map in the EVPN address family (RFC 8212) |
| Remote type-5 imported | `vtysh -c 'show bgp vrf tenant-a ipv4 unicast'`, `ip route show vrf tenant-a` | remote /24 + /32 via the remote VTEP loopback | route present in `show bgp l2vpn evpn route` with `RT:65103:50001` but **missing** from the VRF: RT mismatch (export side) |
| Next hop = originating VTEP | `vtysh -c 'show bgp l2vpn evpn route type 5'` on a leaf | `10.200.0.1x` (leaf loopback) | `10.200.0.1` / `10.200.0.2`: spine rewrote the next hop (no `attribute-unchanged next-hop`) |
| Router MAC / remote VTEP programmed | `vtysh -c 'show evpn rmac vni all'`, `bridge fdb show dev vx<L3VNI>` | `<rmac> dst 10.200.0.13 self extern_learn` | missing → no tunnel to that VTEP |
| Path MTU | `ping -M do -s <tenant MTU − 28>` from the endpoint | 8972 passes, 8973 "message too long" | Linux VTEP replied `Frag needed … mtu = 9450` when the tenant MTU was raised to the fabric MTU; a hardware VTEP would silently drop |
| VXLAN on the wire | `tcpdump -i any udp port 4789` on a spine tap | VNI = tenant L3VNI, outer = leaf loopbacks, inner 9000 B → outer 9050 B | wrong VNI, or packets to a spine loopback |

## Isolate

1. Local leaf first: VNI binding, then the BGP L3VNI table (one entry, intent RT).
2. Remote leaf: is the type-5/type-2 route received (`show bgp l2vpn evpn route`)
   and imported (VRF table)? Received but not imported means an RT mismatch.
   Not received means a session or policy problem.
3. Next hop and RMAC: a next hop that isn't a VTEP points to a spine rewrite.
4. Data plane: MTU, then a capture on the spine tap.

## Remediate

- **RT mismatch:** fix the intent RTs (explicit `65000:<VNI>` on every side) and
  re-render. FRR's *auto* import matches `*:VNI` under eBGP (E7: import-side
  auto still worked), but an auto **export** (`<own AS>:VNI`) is not imported by
  peers with explicit RTs (E7: leaf1 dropped leaf3's routes).
- **Next hop rewritten:** spines need `neighbor <leaf> attribute-unchanged
  next-hop` in `address-family l2vpn evpn` (rendered from intent).
- **`(Policy)`:** apply route-maps in the EVPN address family too.
- **Phantom L3VNI / wrong VRF binding:** render `vrf … vni` and the
  `router bgp <AS> vrf <tenant>` blocks **before** the default `router bgp`
  (holding `advertise-all-vni`). On a live box, `vrf X / no vni N / vni N`
  rebinds forwarding but can leave a phantom entry; redeploy the rendered config.
- **MTU:** tenant MTU + 50 B ≤ fabric MTU (validator enforces it).

## Verify

`make fabric-test`: `test_tenants.py` checks one entry per VNI with the
intent RTs, same-tenant reachability, cross-tenant and tenant→rail
isolation, and the exact path MTU (E7: 61 passed).

## Prevent

- Explicit RTs in intent; a test that fails on any auto RT or duplicate
  VNI entry (`test_every_vni_uses_the_intent_route_targets`).
- Spine EVPN next-hop policy rendered, never hand-added.
- MTU validated in intent before render.
- Pre-deployment offline validation (Batfish) for the underlay. EVPN is not
  part of this repo's Batfish checks (see ADR 0006).
