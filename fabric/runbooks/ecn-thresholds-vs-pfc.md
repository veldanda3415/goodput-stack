# ECN thresholds mis-set relative to PFC XOFF

**Label: INTENT-ONLY**, with one EMULATED reference point (E4). The rule and
numbers come from [`../qos/README.md`](../qos/README.md) and
[`../tools/headroom.py`](../tools/headroom.py). E4 measured Linux RED, not
switch WRED.

## Symptom

- RoCE traffic sees PFC PAUSE under normal incast but few or no CNPs. Jobs
  survive, but PAUSE spreads congestion to innocent flows (head-of-line
  blocking) and the risk of PFC storms grows.
- Or the reverse: ECN marks so early that DCQCN throttles senders far below
  link rate (throughput loss with almost no queue).

## Signals

| Signal | Where | Interpretation |
|---|---|---|
| `kmax_bytes ≥ xoff_threshold_bytes` | intent `qos.ecn` vs `qos.pfc` | invalid: PAUSE can fire before marking reaches Pmax. `fabric.intent.schema.validate` rejects this |
| PFC Tx on priority 3 > 0 while `WRED/ECN marked` stays ~0 on the same queue | SONiC `show pfc counters`, `show queue wredcounters` | marking is not happening before XOFF |
| CNPs (DSCP 48 / TC 6) received per second at senders ≈ 0 during incast | NIC counters, or a switch queue-6 counter | no congestion signal reaching DCQCN |
| ECN marks with throughput far below rate and near-empty queues | WRED counters + port utilization | Kmin too low or Pmax too aggressive |
| EMULATED reference | [E4](../experiments/E4-ecn.md) | at 500 Mbit/s with scaled Kmin/Kmax 1,500/3,000 B (< scaled XOFF 3,750 B), RED marked CE on ECT(0) and TCP reacted with ECE/CWR; SOFT-ROCE packets were CE-marked but no CNPs appeared (rxe has no DCQCN) |

## Isolate

1. Compare the deployed WRED profile with the intent:
   `sonic-cfggen -d --var-json WRED_PROFILE` vs the rendered
   `build/example/sonic/<switch>/config_db.qos.json`.
2. Compare the buffer profile `xoff`/`static_th` with the intent XOFF (3,000,000 B
   design value; headroom from `headroom.py` per cable length).
3. Check that the ECN profile is bound to the lossless queue (3) and that
   endpoints send ECT (`--tclass 106` = DSCP 26 + ECT(0) in E4; `104` is
   Not-ECT and cannot be marked, see E4 "Which packets were CE").

## Remediate

- Fix the intent: Kmin 150,000 B / Kmax 1,500,000 B / Pmax 100% (Cumulus 5.16
  RoCE defaults) under XOFF 3,000,000 B, then render and push. Never hand-edit
  `config_db` on one switch.
- Ensure ECT is set by the RDMA stack's traffic class (tclass) for the RoCE class.

## Verify

- Under a controlled incast, WRED marks rise first and PFC Tx stays near
  zero; CNPs arrive at senders; throughput stays close to line rate.
- The validator test (`fabric/tests/test_qos.py`) passes for the rendered intent.

## Prevent

- Keep the validator rule (ECN Kmax < XOFF) in CI. Render SONiC/NX-OS QoS from
  the same intent. Add an offline check that compares deployed WRED/buffer
  profiles to the render (Batfish does not model buffers; this needs a
  config-diff check).
