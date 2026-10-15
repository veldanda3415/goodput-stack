# docs/

Design records, pinned versions and upstream drafts. Component write-ups live next to their code
(`deploy/gateway/GAPS.md`, `observability/`, `autoscaling/`, `scheduling/`, `benchmarks/results/t4/`).

## Architecture decision records (`adr/`)
| ADR | Decision |
|---|---|
| [0002 — Gateway in the chart](adr/0002-gateway-in-chart.md) | The Gateway is templated in the `inf` chart and the live object adopted; each InferencePool keeps its own `llm-d-router-gateway` EPP release |
| [0003 — Token-aware scoring](adr/0003-token-aware-scorer.md) | Close the size-blind routing gap (#23) by enabling and tuning llm-d's `token-load-scorer`, not by writing a custom plugin |

The choice of agentgateway + Gateway API Inference Extension + the llm-d EPP over a custom router is summarised in the
top-level [README](../README.md) and in [router/README.md](../router/README.md).

## Other
- [environment.md](environment.md): pinned versions (T4/Kaggle engine track, models, local lab), each linked to the run it was read from.
- [upstream/](upstream/): drafts of upstream issues found by the probes (agentgateway ext_proc 10 s cut; EPP decision-latency
  and gateway TTFT metrics). **Drafts, not filed.**
