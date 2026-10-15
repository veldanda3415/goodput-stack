# DRAFT (not filed): hop-cost and TTFT observability for gateway + EPP (#28)

Two small asks from this repo's measurements. Versions: agentgateway v1.6.0, llm-d-router v0.9.0.

## 1. EPP decision latency - exists; the gap is the gateway side
The EPP exports `inference_extension_scheduler_e2e_duration_seconds` (deprecated name; replacement
`llm_d_epp_scheduler_e2e_duration_seconds`, `pkg/epp/metrics/metrics.go`) with buckets 0.1 ms..100 ms. Measured here
(SIMULATED backend, n=100 sequential requests, `scripts/probe_epp_overhead.py`): mean 0.03 ms stock profile, 0.11 ms with
token-load-scorer. The finest bucket (0.1 ms) is coarser than the typical decision, so the histogram can only say
"<= 0.1 ms". Ask (llm-d-router): add buckets below 100 us, or document the sum/count as the intended precision.
That histogram is scheduling only; the full ext_proc round trip (gRPC, body buffering, EPP request handling) is only visible
as the gateway's `request_processing_duration` (`crates/agentgateway/src/telemetry/metrics.rs`).
Ask (agentgateway): a per-ext_proc-call duration histogram labelled by phase (headers/body), so the EPP hop can be separated
from other request processing.

## 2. Gateway TTFT
agentgateway has `gen_ai_server_time_to_first_token` (`telemetry/metrics.rs`, recorded in `telemetry/log.rs`), which we have not
verified for requests routed to an InferencePool backend. Ask: confirm it is populated for InferencePool routes with streaming
responses and document it; if it is not, that is the gap. Our client-side TTFT (`scripts/probe_p8_size_blind.py`) is the
reference to compare against.
