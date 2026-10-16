"""Decode RoCE v2 packets from a classic libpcap file (stdlib only).

Layout: Ethernet / IPv4 / UDP dst 4791 / BTH (12 bytes) / ... / ICRC (4 bytes,
last bytes of the UDP payload). BTH field masks follow the Linux rxe driver,
drivers/infiniband/sw/rxe/rxe_hdr.h (tag linux-msft-wsl-6.18.33.2):

    byte 0      opcode
    byte 1      SE (0x80) | MigReq (0x40) | PadCnt (0x30) | TVer (0x0f)
    bytes 2-3   P_Key
    bytes 4-7   FECN (0x80000000) | BECN (0x40000000) | DestQP (0x00ffffff)
    bytes 8-11  AckReq (0x80000000) | PSN (0x00ffffff)

SOFT-ROCE note: these are rdma_rxe packets on veth links (EMULATED).

Usage: python3 -I bth_decode.py capture.pcap [--limit N] [--json]
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter, defaultdict
from typing import Any, Iterator

ROCE_V2_PORT = 4791
LINKTYPE_ETHERNET = 1
LINKTYPE_LINUX_SLL = 113
LINKTYPE_LINUX_SLL2 = 276

# RC opcodes (IBA transport opcode = class 0b000 for RC); names match Wireshark.
OPCODES = {
    0x00: "RC SEND First", 0x01: "RC SEND Middle", 0x02: "RC SEND Last", 0x04: "RC SEND Only",
    0x06: "RC RDMA WRITE First", 0x07: "RC RDMA WRITE Middle", 0x08: "RC RDMA WRITE Last",
    0x0A: "RC RDMA WRITE Only", 0x0C: "RC RDMA READ Request",
    0x0D: "RC RDMA READ Response First", 0x0E: "RC RDMA READ Response Middle",
    0x0F: "RC RDMA READ Response Last", 0x10: "RC RDMA READ Response Only",
    0x11: "RC Acknowledge", 0x81: "CNP",
}


def pcap_records(data: bytes) -> Iterator[tuple[int, bytes]]:
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise ValueError("not a classic libpcap file (pcapng is not supported)")
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    offset = 24
    while offset + 16 <= len(data):
        _, _, captured, _ = struct.unpack(endian + "IIII", data[offset:offset + 16])
        offset += 16
        yield linktype, data[offset:offset + captured]
        offset += captured


def l3_offset(linktype: int, frame: bytes) -> int | None:
    if linktype == LINKTYPE_ETHERNET:
        ethertype, offset = struct.unpack("!H", frame[12:14])[0], 14
        if ethertype == 0x8100:
            ethertype, offset = struct.unpack("!H", frame[16:18])[0], 18
    elif linktype == LINKTYPE_LINUX_SLL:
        ethertype, offset = struct.unpack("!H", frame[14:16])[0], 16
    elif linktype == LINKTYPE_LINUX_SLL2:
        ethertype, offset = struct.unpack("!H", frame[0:2])[0], 20
    else:
        return None
    return offset if ethertype == 0x0800 else None


def decode(frame: bytes, linktype: int) -> dict[str, Any] | None:
    ip = l3_offset(linktype, frame)
    if ip is None or len(frame) < ip + 20:
        return None
    ihl = (frame[ip] & 0x0F) * 4
    if frame[ip + 9] != 17:
        return None
    tos = frame[ip + 1]
    udp = ip + ihl
    src_port, dst_port, udp_len = struct.unpack("!HHH", frame[udp:udp + 6])
    if dst_port != ROCE_V2_PORT:
        return None
    bth = udp + 8
    if len(frame) < bth + 12:
        return None
    opcode = frame[bth]
    flags = frame[bth + 1]
    pkey = struct.unpack("!H", frame[bth + 2:bth + 4])[0]
    word1, word2 = struct.unpack("!II", frame[bth + 4:bth + 12])
    icrc_offset = udp + udp_len - 4  # last 4 bytes of the UDP payload
    captured_icrc = frame[icrc_offset:icrc_offset + 4] if len(frame) >= icrc_offset + 4 else b""
    return {
        "src": ".".join(str(b) for b in frame[ip + 12:ip + 16]),
        "dst": ".".join(str(b) for b in frame[ip + 16:ip + 20]),
        "dscp": tos >> 2,
        "ecn": tos & 0x03,
        "udp_src_port": src_port,
        "udp_len": udp_len,
        "opcode": opcode,
        "opcode_name": OPCODES.get(opcode, f"0x{opcode:02x}"),
        "se": bool(flags & 0x80),
        "pad_count": (flags & 0x30) >> 4,
        "tver": flags & 0x0F,
        "pkey": f"0x{pkey:04x}",
        "fecn": bool(word1 & 0x80000000),
        "becn": bool(word1 & 0x40000000),
        "dest_qp": word1 & 0x00FFFFFF,
        "ack_req": bool(word2 & 0x80000000),
        "psn": word2 & 0x00FFFFFF,
        "icrc_frame_offset": icrc_offset,
        "icrc": captured_icrc.hex() if captured_icrc else None,
    }


ECN_NAMES = {0: "Not-ECT", 1: "ECT(1)", 2: "ECT(0)", 3: "CE"}


def summarize(packets: list[dict[str, Any]]) -> dict[str, Any]:
    ports_per_qp: dict[int, set[int]] = defaultdict(set)
    for packet in packets:
        ports_per_qp[packet["dest_qp"]].add(packet["udp_src_port"])
    return {
        "packets": len(packets),
        "opcodes": dict(Counter(packet["opcode_name"] for packet in packets)),
        "dscp": dict(Counter(packet["dscp"] for packet in packets)),
        "ecn": dict(Counter(ECN_NAMES[packet["ecn"]] for packet in packets)),
        "udp_src_ports": sorted({packet["udp_src_port"] for packet in packets}),
        "udp_src_ports_per_dest_qp": {f"0x{qp:06x}": sorted(ports) for qp, ports in sorted(ports_per_qp.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pcap")
    parser.add_argument("--limit", type=int, default=10, help="packets to print")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args()
    with open(args.pcap, "rb") as stream:
        data = stream.read()
    packets = [p for linktype, frame in pcap_records(data) if (p := decode(frame, linktype))]
    summary = summarize(packets)
    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        print()
        return
    print("src -> dst | DSCP ECN | UDP sport | opcode | DestQP | PSN | A | ICRC@offset")
    for packet in packets[: args.limit]:
        print(
            f"{packet['src']} -> {packet['dst']} | {packet['dscp']} {ECN_NAMES[packet['ecn']]} | "
            f"{packet['udp_src_port']} | {packet['opcode_name']} | 0x{packet['dest_qp']:06x} | "
            f"{packet['psn']} | {int(packet['ack_req'])} | {packet['icrc']}@{packet['icrc_frame_offset']}"
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
