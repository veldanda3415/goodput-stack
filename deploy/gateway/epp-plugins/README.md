# Token-aware scoring on sim-pool (#23, ADR 0003)

**No plugin is built here.** llm-d-router v0.9.0 already ships `inflight-load-producer` + `token-load-scorer`, so this
directory only holds documentation; the configuration is [`../epp-sim-token-load.values.yaml`](../epp-sim-token-load.values.yaml).
The planned Go module, tests and EPP image were dropped on purpose (see [ADR 0003](../../../docs/adr/0003-token-aware-scorer.md)).

## What it does
The EPP counts, per endpoint, prompt tokens it dispatched and that haven't produced a first token yet. `token-load-scorer`
scores `1 - min(1, tokens / queueThresholdTokens)` (threshold 8192 here, weight 4; queue 2, kv 2, prefix 3 unchanged).
Result (P8, SIMULATED): the long-prompt pod is avoided, probe TTFT 7.75 s -> 0.56 s ([GAPS.md](../GAPS.md) P8).

## Use
```bash
make epp-plugin-test   # server-side dry-run of sim-pool's EPP with the overlay
make epp-plugin-on     # helm upgrade sim-pool with the overlay + restart that EPP only
make epp-plugin-off    # back to epp-sim.values.yaml alone (stock profile) + restart
```
`llamacpp-pool` is never touched. The EPP reads its config only at start, hence the restart.

## Limits
- State is per EPP replica and in memory: other replicas, direct-to-pod load and requests in flight across an EPP restart are invisible.
- Token counts are bytes/4 estimates (about +20% on the P8 prompts); the `vllm` tokenizer backend is not enabled.
- Entries for requests that never produce a first token are reaped after 5 min (janitor), so a leak biases scoring for at most that long.
- Threshold 8192 is sized for the simulator (max-num-seqs 2 x max-model-len 4096). The upstream default (4194304) is a no-op here. Weight 4 was only tested with P8 and P1.
- All results are SIMULATED (llm-d-inference-sim); nothing was run on llama.cpp or a GPU.
