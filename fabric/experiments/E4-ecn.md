# E4 — ECN marking on an EMULATED bottleneck

**Status:** experiment implementation and predictions are in place; results are
added after the run. The lab is an EMULATED veth/Linux-forwarding fabric.
RoCE verbs measurements are separately labeled SOFT-ROCE, not NIC performance.

## Prediction (recorded before the run)

The test shapes `leaf1:eth2` (toward spine2) to 500 Mbit/s and scales Kmin/Kmax
from the QoS intent's 400 Gbit/s target. The raw scaled Kmin is 188 B, below
one 1,500 B packet, and raw Kmax is 1,875 B. The RED renderer floors effective
Kmin to one packet and raises Kmax to twice that minimum: effective Kmin is
1,500 B, effective Kmax 3,000 B, and scaled design XOFF 3,750 B. The Kmax<XOFF
ordering remains intact. These are qdisc tuning inputs for this emulation,
not actual switch buffer or PFC thresholds. The 1 Gbit/s calibration and its
raw data are preserved in [`e4-1gbps-calibration.json`](e4-1gbps-calibration.json).

| Test | Prediction |
|---|---|
| TCP ECN on | RED should mark ECT(0) as CE; TCP should respond with ECE/CWR and retain useful throughput. |
| TCP ECN off | Not-ECT packets should be dropped after RED Kmin; no CE/ECE/CWR response, with lower or less stable throughput. |
| SOFT-ROCE | The 1 Gbit/s calibration carried 0.62 Gbit/s and did not mark; at 500 Mbit/s expect CE marks, but no CNP (BTH opcode `0x81`) or rate reaction because rxe does not implement DCQCN. |
| PFC | No PFC exists in the veth path. At 500 Mbit/s, effective ECN Kmax is 3,000 B versus scaled design XOFF 3,750 B. The hardware intent is ECN Kmax 1,500,000 B versus PFC XOFF 3,000,000 B; [`headroom.py`](../tools/headroom.py) is INTENT-ONLY arithmetic. |

The RED parameter meanings and algorithm follow
[`tc-red(8)`](https://man7.org/linux/man-pages/man8/tc-red.8.html), *ALGORITHM*
and *PARAMETERS*: the average queue is marked between `min` and `max`,
`probability` is the maximum mark probability, `burst` is derived from
`(min + min + max) / (3 * avpkt)`, and `ecn` marks ECN-capable packets while
non-ECT packets are dropped.

## Method

Run `make fabric-e4`. The script derives thresholds from
`fabric/intent/fabric.yaml` rather than duplicating the hardware intent,
installs TBF+RED on `leaf1:eth2`, and removes the temporary root qdisc in a
`finally` block. It compares three 5-second, four-stream iperf3 runs per TCP
condition (`--tos 106` = DSCP 26/ECT(0); `--tos 104` = DSCP 26/Not-ECT),
with ping RTT samples and spine2 tap captures. It then runs `ib_write_bw`
between the two VM endpoints with the same bottleneck and captures UDP 4791.
Raw commands, qdisc counters, packet fields and output are written to
[`e4-results.json`](e4-results.json); bounded pcap artifacts are in `e4/`.

## Measured results

Command: `make fabric-e4` on 2026-10-15. `tc` was iproute2 6.9.0. The shaping
commands, all raw iperf3 JSON, qdisc snapshots, ping output and packet-derived
counts are in [`e4-results.json`](e4-results.json); the initial 1 Gbit/s
calibration is retained in [`e4-1gbps-calibration.json`](e4-1gbps-calibration.json).

TCP client command per trial:

```text
iperf3 -c 10.210.0.22 -B 10.210.0.18 -p 5217 -P 4 -t 5 --tos 106 --json  # ECN on
iperf3 -c 10.210.0.22 -B 10.210.0.18 -p 5217 -P 4 -t 5 --tos 104 --json  # ECN off
ping -n -I 10.210.0.18 -i 0.1 -c 50 10.210.0.22
```

| Condition | Prediction | Measured (repeats 1 / 2 / 3) |
|---|---|---|
| TCP ECN on, DSCP 26/ECT(0) | CE marking; ECE/CWR response; useful throughput | Capture: 103/1200, 129/1200, 103/1200 packets CE; ECE 146/193/124 and CWR 24/33/21. RX 0.402/0.396/0.394 Gbit/s; ping mean RTT 0.525/0.503/0.554 ms. |
| TCP ECN off, DSCP 26/Not-ECT | RED drops; no CE/ECE/CWR; predicted throughput lower or less stable | All 1200 sampled packets per repeat were Not-ECT; ECE/CWR 0/0. RX 0.435/0.445/0.442 Gbit/s; ping mean RTT 0.668/0.549/0.473 ms (repeat 3 max RTT 10.254 ms). |
| SOFT-ROCE `ib_write_bw`, 64 KiB, `-D 3 --tclass 106` | At 500 Mbit/s expect CE; no CNP or DCQCN response | 0.46 Gbit/s reported; 17/1200 sampled packets CE, 1,183 ECT(0), zero CNP opcode `0x81`. Client CPU: 29.02% user, 5.74% system. |
| ECN vs PFC | No PFC in veth; ECN Kmax must precede XOFF | Effective scaled Kmax 3,000 B < scaled XOFF 3,750 B. Hardware intent remains 1,500,000 B < 3,000,000 B; no actual PFC event was possible. |

The median TCP receive rate was 0.396 Gbit/s with ECN and 0.442 Gbit/s
without. Thus the prediction that ECN-off throughput would be lower was not
supported; both conditions were shaped near the 500 Mbit/s limit, and the
no-ECN run instead accumulated many more drops. Median RTT was 0.525 ms on and
0.549 ms off; one off-run reached 10.254 ms max RTT. The RED counters after
the ECN-on trials were `marked=44,024`, `early=3,191`, `pdrop=11,652`; after
the ECN-off trials `marked` remained 44,024 while `early=42,501` and the TBF
drop count was 54,153. These are Linux qdisc counters, not switch ASIC
statistics.

The SOFT-ROCE trial increased RED's marked counter by 11,615 and its TBF drop
count by 202; 17 CE-marked packets appear in the bounded tap sample. The
capture and counters prove the emulated RED mark, but zero CNPs do not by
themselves prove rate control; rxe does not implement DCQCN, and the 0.46
Gbit/s result is bounded by the shaper. The 1 Gbit/s calibration carried
0.62 Gbit/s (command and output preserved in the calibration JSON) and showed
no CE because this single-QP load did not saturate that shaper. Lowering the
rate to 500 Mbit/s was therefore predicted to expose CE before the final run.
The combined pcap artifacts in `e4/` are 1,576,378 bytes.

### Which packets were CE (added after F4 review)

E3 recorded RoCE packets as DSCP 26 / Not-ECT, and RED cannot set CE on
Not-ECT packets (tc-red(8), *PARAMETERS*, `ecn`: non-ECT packets are dropped,
not marked). That is consistent with E4, because the two experiments used
different traffic classes:

- E3 used `--tclass 104`: 104 = `0b011010_00`, DSCP 26 with ECN `00` (Not-ECT).
- E4 used `--tclass 106` on both client and server (`e4-results.json` →
  `roce.command` and `roce.server_command`). 106 = `0b011010_10`, DSCP 26 with
  ECN `10` (ECT(0)). ECT(0) packets are eligible for CE marking.

The 17 CE packets are SOFT-ROCE data, not a side channel. The capture filter
was `udp port 4791`, and decoding [`e4/roce-tclass106.pcap`](e4/roce-tclass106.pcap)
per packet (stdlib decoder in `e3/bth_decode.py`) gives:

| 5-tuple (UDP) | ECN | BTH opcode | Packets |
|---|---|---|---:|
| 10.210.0.18:49390 → 10.210.0.22:4791 | ECT(0) | 0x06/0x07/0x08 WRITE First/Middle/Last | 1,165 |
| 10.210.0.18:49390 → 10.210.0.22:4791 | **CE** | 0x07 RDMA WRITE Middle | **17** |
| 10.210.0.22 → 10.210.0.18:4791 | ECT(0) | 0x11 Acknowledge | 18 |

All CE packets are forward-direction data, which crosses the RED bottleneck
(`leaf1:eth2` egress, captured after it on `spine2:eth1`). The ACKs travel the
reverse direction, which is not shaped, and none are CE. The CE packets occur
in two bursts (packet indices 860–867, 878–887, then 1002 and 1004), about
14 ms into the capture.

Why only 17 of 1,200 while RED's `marked` counter rose by 11,615: the bounded
sample (`-c 1200`, 256-byte snaplen) spans only 0.0199 s of the 3 s run, the
first 20 ms. The queue was still building then. The sample cannot estimate
the run's CE fraction; the qdisc counter is the run-level evidence. The 1 Gbit/s
calibration capture
([`e4/roce-tclass106-1g-calibration.pcap`](e4/roce-tclass106-1g-calibration.pcap))
has the same tuples, with 1,182 ECT(0) data and 18 ECT(0) ACKs, and no CE.
No repeat run was needed. Decode command:
`python3 -I fabric/experiments/e3/bth_decode.py fabric/experiments/e4/roce-tclass106.pcap`
for opcodes, plus a per-packet IPv4/UDP field dump using the same
`pcap_records`/`l3_offset` helpers. **SOFT-ROCE over EMULATED fabric.**

### Failures and corrections

- Initial E4 stopped before traffic because the VM's `fabric` user lacks direct
  sysctl privilege. `sudo -n /usr/sbin/sysctl` succeeded; the original
  `tcp_ecn=2` setting was restored on both guests after every run.
- The first iperf3 attempt refused connections: the server listened on 5217,
  but the client used default port 5201. The client now specifies `-p 5217`.
- Another refusal was caused by passing `vm-exec` into the E3 background helper,
  which already wraps VM commands. Removing that duplicate wrapper made the
  guest server and ping process start correctly.
- RED initially rejected `bandwidth` after the terminal `ecn` option, and a
  two-packet `burst` was rejected as too large. The supported order is
  `bandwidth ... probability ... ecn`, and the tc-red(8) burst formula is
  rounded down to the integer packet count. A raw scaled Kmin below one packet
  is floored to 1,500 B; these effective thresholds and the floor are retained
  in the JSON results.

Do not infer hardware ECN, PFC, or DCQCN behavior from this EMULATED/SOFT-ROCE
test.
