from __future__ import annotations

import struct

from fabric.experiments.e3.bth_decode import decode, pcap_records, summarize


def roce_frame(sport: int, qp: int, psn: int, opcode: int = 0x0A, tos: int = 104, ack: bool = True) -> bytes:
    payload = b"\x00" * 16
    icrc = bytes.fromhex("deadbeef")
    bth = struct.pack("!BBHII", opcode, 0x00, 0xFFFF, qp, (0x80000000 if ack else 0) | psn)
    udp_payload = bth + payload + icrc
    udp = struct.pack("!HHHH", sport, 4791, 8 + len(udp_payload), 0) + udp_payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, tos, 20 + len(udp), 0, 0x4000, 64, 17, 0,
                     bytes([10, 210, 0, 2]), bytes([10, 210, 0, 10]))
    return b"\x02" * 6 + b"\x04" * 6 + b"\x08\x00" + ip + udp


def pcap(frames: list[bytes]) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for frame in frames:
        out += struct.pack("<IIII", 0, 0, len(frame), len(frame)) + frame
    return out


def test_decodes_bth_fields_and_icrc_position() -> None:
    frame = roce_frame(sport=0xC123, qp=0x000011, psn=4242)
    (linktype, raw), = list(pcap_records(pcap([frame])))
    packet = decode(raw, linktype)
    assert packet is not None
    assert packet["dscp"] == 26 and packet["ecn"] == 0
    assert packet["opcode_name"] == "RC RDMA WRITE Only"
    assert packet["dest_qp"] == 0x11 and packet["psn"] == 4242 and packet["ack_req"]
    assert packet["icrc"] == "deadbeef"
    assert packet["icrc_frame_offset"] == len(frame) - 4


def test_summarizes_source_ports_per_qp() -> None:
    frames = [roce_frame(0xC001, 1, 1), roce_frame(0xC001, 1, 2), roce_frame(0xC002, 2, 1)]
    packets = [p for lt, raw in pcap_records(pcap(frames)) if (p := decode(raw, lt))]
    summary = summarize(packets)
    assert summary["udp_src_ports_per_dest_qp"] == {"0x000001": [0xC001], "0x000002": [0xC002]}
