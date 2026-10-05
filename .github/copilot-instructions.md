# goodput-stack Copilot instructions

## Repository status and workflow

This is an early-stage Kubernetes LLM-serving stack. The current tree is primarily a
scaffold: subsystem directories contain `README.md` files and `.gitkeep` placeholders,
not application source, Helm manifests, test code, or dependency manifests. Do not
assume a described component has been implemented; add evidence with the implementation
when making a component operational.

Use the root Makefile for the repository-wide commands that exist:

```bash
make help          # list available repository targets
make check-env     # report versions of required local/cluster tools
make cluster-info  # show active kube context, nodes, and Helm releases
make tree          # print the repository layout
```

There are currently no build, lint, or test targets, and no test framework or
single-test command. When adding one, expose it through `make` and document both the
full-suite and focused-test invocations here.

The expected local environments are k3s on WSL2 for single-node CPU work and k3d on
Podman for multi-node scheduling work. GPU benchmarks run directly on a T4 host, rather
than in the local Kubernetes environment.

## Architecture

The intended system serves open-weight LLMs on Kubernetes within a latency SLO while
minimizing GPU use. Requests enter the `router/` FastAPI gateway, which is meant to
provide an OpenAI-compatible streaming API and select a backend based on model, request
size, latency class, and load. `deploy/` owns the Helm deployment surface for the router
and the llama.cpp/vLLM backends; models are fetched at deployment time and must not be
baked into images.

`autoscaling/` is designed to use KEDA and queue depth or pending requests rather than
CPU utilization. `scheduling/` contains the comparison and scenario material for GPU
allocation approaches (device plugin, DRA, time-slicing, and Kueue quotas). Treat its
GPU resources as simulated unless the relevant artifact explicitly documents otherwise.

`observability/` supplies kube-prometheus-stack configuration, ServiceMonitors, and
Grafana dashboards. The cross-cutting inference signals are time to first token (TTFT),
inter-token latency (ITL), throughput, queue depth, and GPU utilization. `benchmarks/`
contains the load harness, sweep configuration, recorded results, and cost analysis for
concurrency, batch size, and quantization experiments.

`fabric/` is a separate but related AI-network design. Keep its intent model as the
source of truth and generate platform configurations via renderers for FRR, SONiC, and
NX-OS. Its lossless RoCE v2/PFC/DCQCN design, along with fabric telemetry and traffic
experiments, is design/simulation material unless a result says otherwise.

## Evidence and labeling conventions

- Record every benchmark result with its date, hardware, software versions, and complete
  configuration. GPU performance numbers require a real T4 run.
- Clearly label simulated, intent-only, and real measurements in manifests, documentation,
  dashboards, and results. In particular, do not present fake GPUs, PFC/DCQCN behavior,
  or design-only fabric work as measured production behavior.
- Keep related artifacts in their owning subsystem: request-serving code and routing
  configuration in `router/`, deployable chart/value changes in `deploy/`, telemetry
  assets in `observability/`, and reproducible benchmark inputs/results in `benchmarks/`.
