"""PFC headroom calculator (INTENT-ONLY: design arithmetic, not a measurement).

Headroom for one lossless priority on one port is the data that can still
arrive after the receiver decides to send PFC PAUSE, until the sender stops:

    headroom = MTU_R + MTU_S + response + 2 * link_delay

* MTU_R: a maximum-size frame the receiver may already be transmitting when
  the XOFF threshold trips, delaying the PAUSE frame.
* MTU_S: the lossless-priority frame the sender is already transmitting when
  the PAUSE arrives and cannot abort.
* response: data the sender emits while processing PAUSE.
* 2 * link_delay: bytes in flight on the cable, PAUSE travelling upstream
  plus data already on the wire downstream (cable delay x rate, both ways).

Sources:
* Formula and terms: H3C Lossless Network Best Practices (6W102), section
  "Configuring PFC headroom": "in-transit traffic (bytes) = MTU R + MTU s +
  Response + 2*link_delay"; MTU R = 9216 bytes; Response "fixed at 3840
  bytes"; 2*link_delay = 13000 bytes per 100 m at 100 Gbps.
  https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Configure___Deploy/Best_Practices/Lossless_Network_BP-Long/
* Delay model: IEEE 802.1Q-2018 Annex N (Figure N-2), as summarized in
  IEEE 802.1 contribution new-lv-adaptive-pfc-headroom-0121-v02: PFC
  transmission delay must consider a maximum-length frame plus the PFC frame;
  interface and higher-layer delays are implementation dependent.
  https://grouper.ieee.org/groups/802/1/files/public/docs2021/new-lv-adaptive-pfc-headroom-0121-v02.pdf
* Propagation: 5.2 ns/m is the value implied by H3C's table
  (13000 B * 8 / 100 Gb/s = 1.04 us round trip over 100 m), close to the
  usual ~5 ns/m for light in fiber.
* Shared buffer for comparison: NVIDIA SN5000 (Spectrum-4) hardware manual,
  "Introduction": "on-chip fully-shared 128MB packet buffering"; SN5600 has
  64 x 800GbE ports. https://networking-docs.nvidia.com/sn5000hw/introduction

* Rate-dependent response: SONiC "Dynamically Headroom Calculation" HLD,
  section "The well-known formula", quoting IEEE 802.3 31B.3.7 pause_quanta
  a MAC may still transmit after XOFF (1 quantum = 512 bit times):
  100G 394, 200G 453, 400G 905. No 800G value is listed there, so this tool
  reports none for 800G.
  https://github.com/sonic-net/SONiC/blob/824ebe380f4ad580b6b92e083a81eb45d3a5513d/doc/qos/dynamically-headroom-calculation.md

Limitation: H3C's fixed 3840-byte response term comes from a guide for
platforms up to 100 Gbps. At 400/800 Gbps the bytes emitted during a fixed
response time grow with rate; use --response-bytes with the vendor's figure
for the target platform.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass

H3C_MTU_R_BYTES = 9216
H3C_RESPONSE_BYTES = 3840
PROPAGATION_NS_PER_M = 5.2
# The manual says "128MB"; read here as MiB. Using 10^6 changes the ratios
# below by under 5%.
SPECTRUM4_SHARED_BUFFER_BYTES = 128 * 1024 * 1024
SPECTRUM4_PORTS_800G = 64

IEEE_8023_PAUSE_QUANTA = {100: 394, 200: 453, 400: 905}
PAUSE_QUANTUM_BYTES = 512 // 8

SPEEDS_GBPS = (100, 200, 400, 800)
CABLE_LENGTHS_M = (3, 10, 100)


@dataclass(frozen=True)
class Headroom:
    speed_gbps: int
    cable_m: float
    mtu_r: int
    mtu_s: int
    response: int
    link_delay_2x: int
    total: int


def cable_bytes_round_trip(speed_gbps: float, cable_m: float, ns_per_m: float = PROPAGATION_NS_PER_M) -> int:
    """Bytes on the wire during one round trip of the cable (2 * link_delay)."""
    # bits = seconds * bit/s = (2 * m * ns/m * 1e-9) * (Gb/s * 1e9); the 1e-9
    # and 1e9 cancel. Round before ceil so float noise cannot add a byte.
    return math.ceil(round(2 * cable_m * ns_per_m * speed_gbps / 8, 6))


def headroom(
    speed_gbps: int,
    cable_m: float,
    mtu_s: int,
    mtu_r: int = H3C_MTU_R_BYTES,
    response: int = H3C_RESPONSE_BYTES,
    ns_per_m: float = PROPAGATION_NS_PER_M,
) -> Headroom:
    if speed_gbps <= 0 or cable_m < 0 or mtu_s <= 0 or mtu_r <= 0 or response < 0:
        raise ValueError("speed, MTUs must be positive; cable length and response non-negative")
    link = cable_bytes_round_trip(speed_gbps, cable_m, ns_per_m)
    return Headroom(speed_gbps, cable_m, mtu_r, mtu_s, response, link, mtu_r + mtu_s + response + link)


def ieee_response_bytes(speed_gbps: int) -> int | None:
    quanta = IEEE_8023_PAUSE_QUANTA.get(speed_gbps)
    return None if quanta is None else quanta * PAUSE_QUANTUM_BYTES


def switch_total(per_port_priority: int, lossless_ports: int, lossless_classes: int) -> int:
    return per_port_priority * lossless_ports * lossless_classes


def table(mtu_s: int, response: int, ns_per_m: float) -> list[Headroom]:
    return [
        headroom(speed, cable, mtu_s, response=response, ns_per_m=ns_per_m)
        for speed in SPEEDS_GBPS
        for cable in CABLE_LENGTHS_M
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="PFC headroom per port/priority (INTENT-ONLY arithmetic)")
    parser.add_argument("--mtu-s", type=int, default=4200, help="lossless-priority frame bytes (RoCE 4096 MTU + headers)")
    parser.add_argument("--response-bytes", type=int, default=H3C_RESPONSE_BYTES)
    parser.add_argument("--ns-per-m", type=float, default=PROPAGATION_NS_PER_M)
    parser.add_argument("--ports", type=int, default=SPECTRUM4_PORTS_800G, help="lossless ports per switch")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = table(args.mtu_s, args.response_bytes, args.ns_per_m)
    if args.json:
        print(json.dumps([asdict(row) for row in rows], indent=2))
        return
    print(f"MTU_R={H3C_MTU_R_BYTES} MTU_S={args.mtu_s} response={args.response_bytes} "
          f"propagation={args.ns_per_m} ns/m (INTENT-ONLY)")
    print("| Speed | Cable | 2*link_delay (B) | Headroom per port/priority (B) "
          f"| {args.ports} ports x 1 class (MiB) | {args.ports} ports x 2 classes (MiB) "
          "| Headroom with 802.3 31B response (B) |")
    print("|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        one = switch_total(row.total, args.ports, 1) / 2**20
        two = switch_total(row.total, args.ports, 2) / 2**20
        ieee = ieee_response_bytes(row.speed_gbps)
        ieee_total = "n/a (no cited quanta)" if ieee is None else str(row.total - row.response + ieee)
        print(f"| {row.speed_gbps}G | {row.cable_m:g} m | {row.link_delay_2x} | {row.total} "
              f"| {one:.2f} | {two:.2f} | {ieee_total} |")
    buffer_mib = SPECTRUM4_SHARED_BUFFER_BYTES / 2**20
    worst = rows[-1]
    print(f"\nSpectrum-4 shared buffer: {buffer_mib:.0f} MiB. Worst row ({worst.speed_gbps}G, "
          f"{worst.cable_m:g} m) x {args.ports} ports: "
          + ", ".join(
              f"{k} class(es) = {100 * switch_total(worst.total, args.ports, k) / SPECTRUM4_SHARED_BUFFER_BYTES:.1f}%"
              for k in (1, 2, 4, 8)
          ) + " of the shared buffer reserved as headroom")


if __name__ == "__main__":
    main()
