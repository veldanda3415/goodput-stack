# observability/

kube-prometheus-stack, scrape config for the gateway / EPPs / engines, the inference dashboard and the EPP alerts.

## Who measures TTFT (#3)

Three components can time a request, and they measure different things. Measured on the k3s lab
2026-10-14 (sim-pool is **SIMULATED**):

| Component | Metric | Starts | Ends | Includes queue wait? | Pools |
|---|---|---|---|---|---|
| Client | `scripts/stream_client.py`, `autoscaling/loadgen.py` (first non-empty `delta.content`) | before the request is sent | first content token | yes, and gateway + EPP + network | both |
| Gateway (agentgateway v1.6.0) | `agentgateway_request_duration_seconds` | request received | **end of the stream** | yes | both |
| Engine (sim) | `vllm:time_to_first_token_seconds` | request scheduled | first token | **no** (`vllm:request_queue_time_seconds` is separate) | sim-pool only |
| Engine (llama.cpp b11146) | none: no histograms, only `timings.prompt_ms` per response | | | | |

Evidence:
- The gateway histogram ends at the end of the stream: one 120-token streaming request grew its `_sum` by 1.9356 s,
  with client total 1.936 s and client TTFB 0.033 s (curl `-w '%{time_starttransfer} %{time_total}'` + two scrapes of
  `:15020/metrics`). agentgateway exports no TTFT/first-byte histogram for these routes; `upstream_call_duration_seconds`
  has no series. So the dashboard puts **engine TTFT next to gateway e2e**, not next to a gateway TTFT.
- The sim's TTFT leaves out queueing: under 6 parallel streams (`stream_client.py -np 6 --runs 12 --max-tokens 96` through
  the gateway) client TTFT p50 was 1,540.2 ms / p95 2,324.3 ms, while engine TTFT p95 peaked at 0.0855 s and engine
  queue time p50 was 1.34–1.75 s (`evidence/task2-load-sim-pool.txt`, `evidence/panels-20261014-222133.json`).
  Client TTFT ≈ queue time + engine TTFT + gateway/EPP/network.
- `agentgateway_request_processing_seconds` (before the upstream call) includes the EPP ext-proc round trip:
  mean 1.354 ms with the EPP up (n=55) vs 0.21 ms with it scaled to 0 (n=103) (`alert_test.py`,
  `evidence/alert-test-20261014-221617.jsonl`). It is the only proxy for EPP decision latency; the EPP exports none.
