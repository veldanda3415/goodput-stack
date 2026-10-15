# router/

**Not built, by decision.** The original plan was a FastAPI router (OpenAI-compatible API, SSE streaming, routing by
model / request size / latency class / load, edge TTFT/ITL metrics). The stack uses agentgateway + the Gateway API
Inference Extension + the llm-d EPP instead ([deploy/gateway/](../deploy/gateway/), [ADR 0002](../docs/adr/0002-gateway-in-chart.md)):
engine-aware pod picking (queue, KV cache, prefix) is what inference teams run, and rebuilding it would invite
"why not the standard stack?".

Gaps found by probing that stack are closed with its own extension points where possible: size-blind routing (#23) was
fixed by enabling llm-d's `token-load-scorer` ([ADR 0003](../docs/adr/0003-token-aware-scorer.md)). Request-size / SLO-based
*pool* choice across CPU and GPU pools (#11, [GAPS.md](../deploy/gateway/GAPS.md) P5) is still open; upstream's
`context-length-aware` plugin is the first thing to evaluate before anything custom.
