# goodput-stack Copilot instructions

## Repository status and workflow

goodput-stack serves open-weight LLMs on Kubernetes within a latency SLO. Routing is not built
here: the repo integrates, probes and documents the gaps in agentgateway v1.6.0 + the Gateway API
Inference Extension (InferencePool) + the llm-d endpoint picker (EPP, `llm-d-router-gateway`
v0.9.0). The README's Repository table is the source of truth for status.

In use:

- `deploy/`: Helm chart `deploy/charts/inference` (release `inf`: llama.cpp, the vLLM simulator
  and the Gateway), per-env values (k3s, k3d) and the release flow (`deploy/release.sh`).
- `deploy/gateway/`: EPP values, one `llm-d-router-gateway` release per InferencePool
  (`epp-sim.values.yaml`, `epp-llamacpp.values.yaml`), and `GAPS.md` with the probe findings.
- `scripts/`: probes and smoke tests; one-line index in `scripts/README.md`.
- `benchmarks/`: the engine suite (`benchmarks/engine/`) against llama.cpp and the simulator,
  with recorded provenance. The system suite (`benchmarks/system/`) is planned.

Started: `docs/` (ADRs). Planned, not built: `observability/`, `autoscaling/`, `scheduling/`,
`fabric/`. `router/` is a placeholder and not built. Do not assume a planned component exists;
add evidence with the implementation when making one operational.

Use the root Makefile (`make help` lists every target with its help text). The important ones:

```bash
make help                 # List targets
make check-env            # Print versions of the tools this repo uses
make cluster-info         # Show current kube context, nodes and Helm releases
make venv                 # Create .venv with benchmark deps

# deploy (inference chart; ENV=k3s|k3d, default k3s)
make deploy ENV=k3s       # Upgrade flow: lint -> diff -> confirm -> upgrade -> helm test
make deploy-lint          # helm lint with the ENV's values
make deploy-diff          # What an upgrade would change on the live cluster (prints "no changes" if none)
make deploy-test          # helm test against the ENV's cluster

# gateway EPPs (one llm-d-router-gateway release per InferencePool)
make epp-diff             # Render each EPP release and dry-run it against the cluster (server-side)
make epp-deploy           # helm upgrade --install both EPP releases from deploy/gateway/epp-*.values.yaml, then restart

# gateway probes (findings in deploy/gateway/GAPS.md)
make probe-p7             # P7: delete the agentgateway pod mid-stream (llamacpp-pool), 3 runs
make probe-burst          # P9: N concurrent sim-pool requests inside one EPP refresh vs spaced control (SIMULATED)

# benchmarks (engine suite)
make bench-engine EXP=ttft      # Engine benchmark (direct llama-server)
make bench-engine-all           # Run every engine experiment back to back + index report
make bench-engine-list          # List engine experiments
make bench-engine-dry EXP=ttft  # Show sweep points and server commands for EXP
make bench-sim EXP=ttft         # Engine experiment against the k3s vLLM simulator
make bench-sim-all              # Every simulator experiment back to back + index report
make bench-compare A=<run> B=<run>  # Two runs side by side
```

There is no unit-test framework. Chart checks are `make deploy-lint`, `make deploy-diff` and
`make deploy-test` (`helm test`); probes P1-P3 are run directly from `scripts/` (see
`scripts/README.md`). When adding a test target, expose it through `make` and document both the
full-suite and focused invocations here.

The expected local environments are k3s on WSL2 for single-node CPU work and k3d on Podman for
multi-node scheduling work. GPU benchmarks run directly on a T4 host, rather than in the local
Kubernetes environment.

## Architecture

The system serves open-weight LLMs on Kubernetes within a latency SLO while minimizing GPU use.
Requests enter agentgateway (Gateway `inference-gateway`, defined in the `inf` chart). An HTTPRoute
sends them to an InferencePool, and that pool's EPP (via ext-proc) picks the backend pod from
engine metrics: queue depth, KV-cache use and prefix-cache affinity. The EPP's scoring is
llm-d's work; this repo deploys and configures it (ADR 0002, `deploy/gateway/`).

Two pools today:

- `sim-pool`: llm-d inference sim (SIMULATED vLLM, no model), the default route.
- `llamacpp-pool`: llama.cpp on CPU (real numbers), selected with header `x-pool: cpu`. No KV
  metric, so its EPP scores on queue and prefix only.

`router/` is a placeholder, kept only in case the EPP cannot do request-size / SLO routing (#11).
vLLM runs only on a T4 outside the cluster (planned). Models are fetched at deployment time and
must not be baked into images.

`autoscaling/` is designed to use KEDA and queue depth or pending requests rather than CPU
utilization. `scheduling/` will contain the comparison and scenario material for GPU allocation
approaches (device plugin, DRA, time-slicing, and Kueue quotas). Treat its GPU resources as
simulated unless the relevant artifact explicitly documents otherwise.

`observability/` will supply kube-prometheus-stack configuration, ServiceMonitors, and Grafana
dashboards. The cross-cutting inference signals are time to first token (TTFT), inter-token
latency (ITL), throughput, queue depth, and GPU utilization. `benchmarks/` contains the load
harness, sweep configuration, recorded results, and cost analysis.

`fabric/` is a separate but related AI-network design. Keep its intent model as the source of
truth and generate platform configurations via renderers for FRR, SONiC, and NX-OS. Its lossless
RoCE v2/PFC/DCQCN design, along with fabric telemetry and traffic experiments, is
design/simulation material unless a result says otherwise.

## Evidence and labeling conventions

- Record every benchmark result with its date, hardware, software versions, and complete
  configuration. GPU performance numbers require a real T4 run.
- Clearly label simulated, intent-only, and real measurements in manifests, documentation,
  dashboards, and results. In particular, do not present fake GPUs, PFC/DCQCN behavior,
  the vLLM simulator, or design-only fabric work as measured production behavior.
- Never describe the gateway or EPP as built by this project; they are integrated, configured
  and probed here.
- Keep related artifacts in their owning subsystem: deployable chart/value changes in `deploy/`,
  EPP values and gateway findings in `deploy/gateway/`, probes in `scripts/`, telemetry assets in
  `observability/`, and reproducible benchmark inputs/results in `benchmarks/`.
