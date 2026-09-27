# goodput-stack

Serve open-weight LLMs on Kubernetes within a latency SLO using the fewest GPUs:
SLO-aware routing, queue-driven autoscaling, GPU sharing and a lossless AI fabric,
measured by TTFT, ITL and cost per million tokens.

> **Status:** work in progress (Week 1). Nothing below is claimed as done until it's
> in the repo with evidence.

## Components
| Area | What | Dir |
|------|------|-----|
| Gateway | FastAPI, OpenAI-compatible, streaming, SLO-aware routing | `router/` |
| Backends | llama.cpp (CPU), vLLM (GPU, T4), vLLM simulator (in-cluster) | `deploy/` |
| Autoscaling | KEDA on queue depth | `autoscaling/` |
| GPU scheduling | device plugin vs DRA, time-slicing, Kueue quotas (simulated GPUs) | `scheduling/` |
| Observability | Prometheus + Grafana: TTFT, ITL, throughput, queue depth, GPU util | `observability/` |
| Benchmarks | concurrency × batch × quantization, cost per 1M tokens | `benchmarks/` |
| AI fabric | intent-driven leaf-spine, eBGP unnumbered, RoCE v2 lossless design | `fabric/` |

## Environment
- Local: k3s on WSL2 (single node, CPU only); k3d on Podman for multi-node scheduling work.
- GPU: free Kaggle/Colab T4 (16 GB, FP16/INT4). Benchmarks run on the T4 host directly.

## Ground rules
- Every benchmark number comes from a recorded run (date, hardware, versions, config).
- Anything simulated or intent-only (fake GPUs, PFC/DCQCN) is labeled as such.

## Quick start
```bash
make help
make check-env
```
