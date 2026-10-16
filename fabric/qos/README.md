# Lossless RoCE v2 QoS design (INTENT-ONLY)

The `qos` section of [`../intent/fabric.yaml`](../intent/fabric.yaml) describes
a lossless RoCE v2 design for a hardware leaf-spine. The renderer turns it into:

- `fabric/build/sonic/<switch>/config_db.qos.json`: SONiC `config_db`
  fragments for each switch. **INTENT-ONLY**: these have never been loaded
  on a SONiC switch. The committed review copy is in
  [`../build/example/sonic/`](../build/example/sonic/).
- `fabric/build/hosts/<host>-qos.sh`: a Linux `tc` equivalent that runs on
  the lab hosts' rail NICs at deploy time. It is **EMULATED**: it classifies
  packets by DSCP into the matching band. It provides no PFC, no buffers, and
  no ECN marking, because veth has none of those. ECN marking with `tc` RED is
  later work.

## Classes

| Class | DSCP | TC / queue | Priority group | Behavior |
|---|---:|---:|---:|---|
| RoCE | 26 | 3 | 3 | lossless: PFC on priority 3, ECN/WRED on queue 3, DWRR 50 |
| CNP | 48 | 6 | 0 | strict priority, lossy |
| default | all other values | 0 | 0 | lossy, DWRR 50 |

Source: NVIDIA Cumulus Linux 5.16, *RDMA over Converged Ethernet (RoCE)*,
default RoCE configuration table. It lists RoCE as DSCP 26 → switch priority 3
→ TC 3 with DWRR 50%, CNP as DSCP 48 → priority 6 → TC 6 with strict priority,
other traffic as TC 0 with DWRR 50%, and PFC on priority 3 in lossless mode:
<https://docs.nvidia.com/networking-ethernet-software/cumulus-linux-516/Layer-1-and-Switch-Ports/Quality-of-Service/RDMA-over-Converged-Ethernet-RoCE/>.
Cumulus 5.16 is the release before the newest listed docs version (5.17).

## ECN must mark before PFC pauses

DCQCN reacts to ECN: the switch marks CE, the receiver NIC returns a CNP, and
the sender NIC cuts its rate. PFC is the backstop. PAUSE stops the entire
priority on the link, including flows that are not causing congestion. This
can cause head-of-line blocking, congestion spreading, and PFC storms or
deadlock. The marking threshold must therefore be reached well before the
ingress PG threshold that sends XOFF. That gives end-to-end rate control time
to act, so PAUSE fires only for bursts that ECN cannot absorb. The validator
rejects intent where `ecn.kmax_bytes >= pfc.xoff_threshold_bytes`. It also
rejects intent with no CNP class or with a lossless class that lacks an
enabled PFC priority.

| Field | Value | Source |
|---|---:|---|
| ECN Kmin | 150,000 B | Cumulus 5.16 RoCE page, `nv show qos roce` `min-threshold 146.48 KB`; "system-level ECN minimum threshold value intended for programming is 150,000 bytes" |
| ECN Kmax | 1,500,000 B | same page, `max-threshold 1.43 MB` (1.43 MiB ≈ 1,500,000 B) |
| ECN Pmax | 100 % | same page, `probability 100` |
| PFC XOFF threshold (`static_th`) | 3,000,000 B | **design choice**, 2 × Kmax; no vendor default is cited |
| `xon`, `size` | 2288 B, 1248 B | example `pg_lossless_40000_5m_profile` in SONiC 202511 `Configuration.md`, *Buffer profile*; platform-specific in production |
| PFC watchdog | drop, 200 ms detect, 200 ms restore, 200 ms poll | `sonic-utilities` 202511 `pfcwd/main.py` (`DEFAULT_DETECTION_TIME`, `DEFAULT_RESTORATION_TIME`, `DEFAULT_POLL_INTERVAL`, `DEFAULT_ACTION`) |
| Cable length | fabric 10 m, host 3 m | design choice; per-link overrides in `qos.cable_length_m.links` |
| Port MTU / RoCE MTU | 9100 / 4096 | design choice; RoCE path MTUs are 256–4096 |

The schema also enforces the SONiC YANG ranges for the watchdog:
`detection_time` 100–5000 ms, `restoration_time` 100–60000 ms, and
`POLL_INTERVAL` 100–1000 ms (`sonic-pfcwd.yang`, 202511).

## Headroom (`BUFFER_PROFILE.xoff`)

[`../tools/headroom.py`](../tools/headroom.py) computes the PFC headroom for
each port and priority. The renderer applies it at the intent's
`target.port_speed_gbps` (400G) and the cable length of each port. It takes
the larger of two values. The first uses H3C's fixed 3840 B response term. The
second uses IEEE 802.3 31B pause quanta for the speed (905 quanta × 64 B at
400G), as quoted by the SONiC dynamic-headroom HLD. For a 400G leaf, the
result is `xoff` = 72,780 B on 3 m host ports and 76,420 B on 10 m fabric
ports. Run `make fabric-headroom` to print the full 100–800G × 3/10/100 m
table and its sources.

## SONiC fields used and where they are documented

All table and field names come from sonic-buildimage branch `202511`
(commit `649c3542d119cc22e7760b40baf46fdb41277c6b` at the time of writing).
This is the release before `202605`.
[`src/sonic-yang-models/doc/Configuration.md`](https://github.com/sonic-net/sonic-buildimage/blob/202511/src/sonic-yang-models/doc/Configuration.md)
and the YANG models in
[`src/sonic-yang-models/yang-models/`](https://github.com/sonic-net/sonic-buildimage/tree/202511/src/sonic-yang-models/yang-models):

| Table | Fields rendered | Doc section / YANG |
|---|---|---|
| `DSCP_TO_TC_MAP` | `"<dscp>": "<tc>"` for all 64 DSCPs | *DSCP_TO_TC_MAP* |
| `TC_TO_QUEUE_MAP` | `"<tc>": "<queue>"` | *TC to Queue map* |
| `TC_TO_PRIORITY_GROUP_MAP` | `"<tc>": "<pg>"` | *TC to Priority group map* |
| `MAP_PFC_PRIORITY_TO_QUEUE` | `"<prio>": "<queue>"` | *MAP_PFC_PRIORITY_TO_QUEUE* |
| `PORT_QOS_MAP` | `dscp_to_tc_map`, `tc_to_queue_map`, `tc_to_pg_map`, `pfc_to_queue_map`, `pfc_enable`, `pfcwd_sw_enable` | *Port QoS Map*; `sonic-port-qos-map.yang` |
| `SCHEDULER` | `type` (`STRICT`/`DWRR`), `weight` | *Scheduler*; `sonic-scheduler.yang` |
| `QUEUE` | `scheduler`, `wred_profile` | *Queue*; `sonic-queue.yang` |
| `WRED_PROFILE` | `ecn: ecn_all`, `wred_{green,yellow,red}_enable`, `{color}_min_threshold`, `{color}_max_threshold`, `{color}_drop_probability` | *WRED_PROFILE*; `sonic-wred-profile.yang` |
| `BUFFER_PROFILE` | `pool`, `xoff`, `xon`, `size`, `static_th` | *Buffer profile*; `sonic-buffer-profile.yang` |
| `BUFFER_PG` | `"<port>\|<pg>": {"profile": ...}` | *BUFFER_PG* |
| `CABLE_LENGTH` | `"<port>": "<n>m"` | *Cable length* |
| `PFC_WD` | per port `action`, `detection_time`, `restoration_time`; `GLOBAL` `POLL_INTERVAL` | `sonic-pfcwd.yang` (not in `Configuration.md`) |
| `PORT` | `mtu`, `speed` | *Port* |

Not rendered: `BUFFER_POOL` sizes, lossy ingress/egress profiles, and the
port-name mapping. These are platform/HwSKU specific. Port names use a
placeholder `ethN → Ethernet{(N-1)×8}` (`qos.target.sonic_port_stride`); a
real deployment takes names from the platform's `port_config.ini`.
