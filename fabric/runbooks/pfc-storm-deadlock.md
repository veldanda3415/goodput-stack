# PFC storm / deadlock and the PFC watchdog

**Label: INTENT-ONLY.** The lab has no PFC (veth has no pause frames or
switch buffers). Commands are SONiC CLI from the sonic-utilities
*Command Reference* (202511, `doc/Command-Reference.md`, sections *PFC*,
*PFC Watchdog Commands*, *Queue counters*). Watchdog defaults come from the
intent ([`../intent/fabric.yaml`](../intent/fabric.yaml) `qos.pfc_watchdog`,
cited in [`../qos/README.md`](../qos/README.md)). Nothing here was run on a switch.

## Symptom

- A collective job stalls entirely, or many jobs slow at once across several
  leaves, with no link down and no BGP/BFD change.
- RoCE throughput on the lossless priority (3) drops to near zero on the
  victim ports, while non-RoCE traffic on other queues may still flow.

## Signals

| Signal | Where | Meaning |
|---|---|---|
| PFC PAUSE frames received keep rising on a port while its egress queue 3 TX stays flat | `show pfc counters` (Rx/Tx per priority), `show queue counters Ethernet<N>` | the port is held paused: storm victim |
| One port *sending* a continuous stream of PAUSE frames on priority 3 | `show pfc counters` (Tx PFC3) on the downstream switch | storm source (often a stuck NIC/host that stopped draining) |
| Watchdog storm detected / restored events and drop counters | `pfcwd show stats`, syslog `PFC Watchdog storm detected` | watchdog acted (intent: action `drop`, detect 200 ms, restore 200 ms, poll 200 ms) |
| Paused queue across a cycle of switches with no host involvement | queue counters on every hop of a loop | deadlock (cyclic buffer dependency), e.g. after a routing loop or a down-up path |
| Lab analogue (EMULATED) | E6 leaf-loss / silent-loss rows | what a stalled ring looks like in step time (stalls ≥ 10 s); the *cause* there is loss, not PAUSE |

## Isolate

1. Rank ports by PFC Tx on priority 3 (`show pfc counters`). Follow the
   highest Tx toward the edge: switch → leaf → host port. The source is
   usually the last hop that *sends* PAUSE but *receives* none.
2. On the host behind that port, check the NIC: RX buffer full or out of
   receive WQEs; a stuck driver; `ethtool -S` `rx_prio3_pause` /
   `tx_prio3_pause` (vendor counter names vary).
3. Distinguish storm from deadlock. A storm has a source. A deadlock is a
   cycle of paused queues with no source, usually started by a transient
   routing loop or a mis-set lossless class on an uplink.

## Remediate

- Let the watchdog contain it: `pfcwd` drops (intent action `drop`) on the
  stormed queue after 200 ms, which turns a fabric-wide stall into local
  loss that RoCE retransmits. Confirm with `pfcwd show stats`.
- Isolate the source host or NIC: shut the host port, or drain the node from
  the scheduler so its job fails fast instead of stalling the fabric.
- For a deadlock, break the cycle by fixing the routing loop. As a last
  resort, disable lossless on the affected priority for that link (a config
  change through intent → render, not a hand edit).

## Verify

- PFC Tx/Rx counters on priority 3 stop increasing faster than normal
  background; `pfcwd show stats` shows `restored`.
- Collective step time returns to its baseline (the E6-style step-time
  metric, measured from per-pair receiver bytes).

## Prevent

- Keep ECN marking well below XOFF so DCQCN reacts before PAUSE (validator
  rule `ecn.kmax_bytes < pfc.xoff_threshold_bytes`;
  [`ecn-thresholds-vs-pfc.md`](ecn-thresholds-vs-pfc.md)).
- Watchdog enabled on every lossless port (`PORT_QOS_MAP.pfcwd_sw_enable`
  in the rendered SONiC fragment).
- Only one lossless priority (intent `qos.pfc.priorities: [3]`); never lossless
  on host-to-host loops; headroom sized from cable length
  ([`../tools/headroom.py`](../tools/headroom.py)).
- Alert on the PFC Tx rate per port and on watchdog events, not only on link state.
