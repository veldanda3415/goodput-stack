# Fabric runbooks

Each runbook follows the same layout: symptom → signals (the exact metric or
command from this lab's exporter or FRR, where one exists) → isolate →
remediate → verify → prevent. The label says how much of the runbook was
exercised:

- **MEASURED-IN-LAB**: reproduced in the EMULATED lab; the runbook links to the
  experiment and raw evidence. Timings are Linux/FRR on veth, not switch ASIC
  numbers.
- **INTENT-ONLY**: derived from the intent, cited vendor documentation, and
  arithmetic. Nothing was run, because the lab has no PFC, buffers, or PHY.

| Runbook | Problem | Label | Evidence |
|---|---|---|---|
| [bgp-session-down.md](bgp-session-down.md) | BGP session down: ASN or interface mismatch | MEASURED-IN-LAB (F1 drill) | [F1 bring-up](../results/f1-bringup.md); offline equivalent in [Batfish](../batfish/README.md#negative-tests) |
| [link-down-bfd-flap.md](link-down-bfd-flap.md) | Leaf–spine link down, silent loss, or flapping; BFD | MEASURED-IN-LAB | [E6](../experiments/E6-failure-drills.md), [E2](../experiments/E2-bfd-convergence.md) |
| [spine-leaf-loss.md](spine-leaf-loss.md) | Spine or leaf loss and its blast radius per host/rail/tenant | MEASURED-IN-LAB | [E6](../experiments/E6-failure-drills.md) |
| [silent-degradation.md](silent-degradation.md) | "Step time +30%, no errors": loss on one uplink with the link up | MEASURED-IN-LAB (detection partial: 2/3 by drops, 1/3 by share) | [E6](../experiments/E6-failure-drills.md#silent-degradation-finding-it-without-being-told), [panel exports](../telemetry/) |
| [ecmp-imbalance.md](ecmp-imbalance.md) | ECMP imbalance / hash polarization | MEASURED-IN-LAB | [E5 + shaped rerun](../experiments/E5-collective-entropy.md#shaped-uplinks-rerun), [E1](../experiments/E1-ecmp-hash.md) |
| [evpn-tenant-unreachable.md](evpn-tenant-unreachable.md) | EVPN tenant can't reach its peer (RT mismatch, next hop rewritten, MTU, VNI binding) | MEASURED-IN-LAB | [E7](../experiments/E7-evpn-tenancy.md) |
| [pfc-storm-deadlock.md](pfc-storm-deadlock.md) | PFC storm / deadlock and the PFC watchdog | INTENT-ONLY | intent `qos.pfc_watchdog`, [QoS README](../qos/README.md) |
| [ecn-thresholds-vs-pfc.md](ecn-thresholds-vs-pfc.md) | ECN thresholds mis-set relative to PFC XOFF | INTENT-ONLY (+ EMULATED E4 reference) | [`headroom.py`](../tools/headroom.py), [E4](../experiments/E4-ecn.md) |
| [fec-crc-errors.md](fec-crc-errors.md) | FEC / CRC errors on a link | INTENT-ONLY | lab analogue: [silent-degradation.md](silent-degradation.md) |

Telemetry used by the MEASURED runbooks: `make telemetry-up` (Python exporter +
standalone Prometheus) and [`observability/dashboards/fabric.json`](../../observability/dashboards/fabric.json),
see [`telemetry/README.md`](../telemetry/README.md).
