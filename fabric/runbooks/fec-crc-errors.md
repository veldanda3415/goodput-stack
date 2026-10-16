# FEC / CRC errors on a link

**Label: INTENT-ONLY.** veth links have no PHY, FEC, or CRC. The lab cannot
produce these counters. The closest EMULATED analogue is
[silent degradation](silent-degradation.md) (random loss with the link up),
measured in [E6](../experiments/E6-failure-drills.md). Commands are SONiC
CLI from the sonic-utilities *Command Reference* (202511, *Interfaces*
section: `show interfaces counters`, `show interfaces counters errors`,
`show interfaces transceiver`, `show interfaces fec status`) and Linux
`ethtool -S` / `ethtool --show-fec`.

## Symptom

- Step time up 10–40% on jobs whose flows cross one particular link, with no
  link flap and no BGP/BFD event. This is the same shape as E6's 1% loss row.
- RDMA NICs report rising retransmissions or out-of-sequence NAKs on some QPs.

## Signals

| Signal | Where | Meaning |
|---|---|---|
| `RX_ERR` / FCS (CRC) errors increasing on one port | `show interfaces counters errors` | frames corrupted beyond FEC's ability: dropped at the receiver |
| FEC corrected codewords rising fast, uncorrectable > 0 | `show interfaces counters fec-stats` (where supported), `ethtool -S` | link margin eroding; uncorrectable codewords become CRC drops |
| FEC mode mismatch (e.g. RS vs none) between ends | `show interfaces fec status` on both ends | link may come up but with high errors, or not at all at 100G+ |
| Optics DOM out of range (RX power, temperature) | `show interfaces transceiver eeprom --dom` | dirty or failing optic or cable |
| Uplink share and drops-per-MB skewed toward one port | dashboard row "EMULATED silent degradation signals" (lab) | how the lab finds the equivalent loss without PHY counters |

## Isolate

1. Rank ports by CRC/FEC-uncorrectable rate. Errors are counted at the
   **receiving** end: a dirty transmitter on switch A shows errors on switch B.
2. Check both ends' FEC mode and optics DOM; swap or clean optics if RX power
   is low.
3. Confirm the impact by comparing that link's ECMP share and its retransmits
   with its sibling (E6 method).

## Remediate

- Take the link out of service gracefully: shut it, or raise its BGP cost and
  drain it. ECMP moves flows to the siblings (E6 link-down row: carrier-down
  removal took < 0.1 s in the lab).
- Clean or replace the optic or cable; align the FEC mode with the intent.
  Return the link to service only after counters stay clean for a soak period.

## Verify

- CRC/FEC-uncorrectable counters flat for a soak window; corrected-codeword
  rate back to the fleet baseline.
- Step time back to baseline; per-uplink share back to ~0.5 per ECMP member.

## Prevent

- Alert on rate of change of FEC corrected/uncorrectable and CRC, not just
  on link down. A link can be "up" and still cost 30% step time (E6).
- Keep FEC mode in intent per port speed and render it (not modeled in this
  lab's intent yet).
- Run optics DOM thresholds as alerts.
