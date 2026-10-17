# docs/

Design records, pinned versions and upstream drafts. Component write-ups live next to their code
(`deploy/gateway/GAPS.md`, `observability/`, `autoscaling/`, `scheduling/`, `benchmarks/results/t4/`, `fabric/DESIGN.md`).

## Architecture decision records (`adr/`)
| ADR | Decision |
|---|---|
| [0002 — Gateway in the chart](adr/0002-gateway-in-chart.md) | The Gateway is templated in the `inf` chart and the live object adopted; each InferencePool keeps its own `llm-d-router-gateway` EPP release |
| [0003 — Token-aware scoring](adr/0003-token-aware-scorer.md) | Close the size-blind routing gap (GAPS.md P8) by enabling and tuning llm-d's `token-load-scorer`, not by writing a custom plugin |
| [0004 — Fabric intent and renderer](adr/0004-fabric-intent-render.md) | One vendor-neutral intent file is the fabric's source of truth; configs, host setup and topology are rendered from it |
| [0005 — Backend topology](adr/0005-backend-topology.md) | Rail-optimized leaf-spine for the scale-out backend (CALCULATED sizing at 256 / 2,048 GPUs) |
| [0006 — Multi-NOS render + Batfish](adr/0006-multi-nos-render-batfish.md) | Render FRR and NX-OS from the same intent and validate offline with Batfish before deploy |

The choice of agentgateway + Gateway API Inference Extension + the llm-d EPP over a custom router is summarised in the
top-level [README](../README.md) and in [router/README.md](../router/README.md).

## Other
- [gaps.md](gaps.md): what could not be done here (RDMA/RoCE, hardware, single node, upstream limits). `#N` references point here.
- [environment.md](environment.md): pinned versions (T4/Kaggle engine track, models, local lab), each linked to the run it was read from.
- [upstream/](upstream/): drafts of upstream issues found by the probes (agentgateway ext_proc 10 s cut; EPP decision-latency
  and gateway TTFT metrics). **Drafts, not filed.**
