# router/

FastAPI gateway: OpenAI-compatible API, SSE streaming, routing by model / request size / latency class / load, edge TTFT/ITL metrics. **Not built:** the stack uses agentgateway + the llm-d EPP instead ([deploy/gateway/](../deploy/gateway/), [ADR 0002](../docs/adr/0002-gateway-in-chart.md)). Revisit for SLO / request-size routing if the EPP path can't do it (#11, [GAPS.md](../deploy/gateway/GAPS.md) P5).
