# ADR 0003 — Token-aware scoring for sim-pool/llamacpp-pool (#23)

- **Status:** part 1 (upstream survey) done 2026-10-15. Part 2 (design) below.
- **Decision (from the survey): do not build a scorer. Configure and evaluate the upstream
  `inflight-load-producer` + `token-load-scorer`, which ship in the v0.9.0 EPP image we already run.**

All paths are in `github.com/llm-d/llm-d-router` at tag `v0.9.0` (the `app version` of chart
`llm-d-router-gateway` v0.9.0; image `ghcr.io/llm-d/llm-d-router-endpoint-picker:v0.9.0`), read from a
`git clone --branch v0.9.0`. Its `go.mod` pins `sigs.k8s.io/gateway-api-inference-extension v1.5.0`, but only for the
API types (`api/v1`); the plugin framework lives in the llm-d-router repo itself (`pkg/epp/framework/`).

## Part 1 — Upstream survey

### 1. What ships, and what our EPP runs

Registered in-tree plugins: `cmd/epp/runner/runner.go` `registerInTreePlugins()` (lines ~481-560). Under
`pkg/epp/framework/plugins/`:

| Kind | Types in v0.9.0 |
|---|---|
| scorers (`scheduling/scorer/`) | `queue-scorer`, `kv-cache-utilization-scorer`, `prefix-cache-scorer`, `precise-prefix-cache-scorer`, `running-requests-size-scorer`, `load-aware-scorer`, `active-request-scorer`, `token-load-scorer`, `context-length-aware`, `latency-scorer`, `lora-affinity-scorer`, `no-hit-lru-scorer`, `session-affinity-scorer`, `mm-cache-affinity-scorer` |
| filters (`scheduling/filter/`) | `by-label` / label-selector, `session-affinity-filter`, `prefix-cache-affinity-filter`, `slo-headroom-tier-filter`, encode/decode/prefill role filters |
| pickers (`scheduling/picker/`) | `max-score-picker`, `random-picker`, `weighted-random-picker` |
| profile handlers | `single-profile-handler`, `disagg-profile-handler`, `data-parallel-profile-handler` |
| data producers (`requestcontrol/dataproducer/`) | `token-producer` (tokenizer), `inflight-load-producer`, approximate/precise prefix producers, `predicted-latency-producer`, `session-id`, multimodal |
| admitters / flow control | `latency-slo-admitter`, probabilistic admitter, utilization + concurrency saturation detectors, EDF / FCFS / SLO-deadline ordering, fairness policies |

**What our sim-pool EPP runs** (live: `kubectl -n inference get cm sim-pool-epp` and the EPP startup log line
`EPP config after phase two`): `single-profile-handler`, one profile `default`, `max-score-picker`, no filters,
`queue-scorer` ×2 + `kv-cache-utilization-scorer` ×2 + `prefix-cache-scorer` ×3. The framework auto-creates
`approx-prefix-cache-producer` and `token-producer` (log: `auto-created default producer`). Source of the weights:
the chart's `default-plugins.yaml`, not our values file. Tie break: `maxscore/picker.go` shuffles equal-scored
endpoints (random tie-break).

How the scores behave (read, then measured in P8):

- `queue-scorer` (`scorer/queuedepth/queue.go`) is **min-max over `WaitingQueueSize` only**: the pod with the shortest
  waiting queue gets 1, the longest 0, all equal gets 1 for everyone. It ignores running requests and request size.
- `kv-cache-utilization-scorer` = `1 − kv_cache_usage_perc`.
- `prefix-cache-scorer` scores the approximate prefix match; unique prompts neutralise it (as in P1).

### 2. Is anything already size- or token-aware? **Yes. #23 is covered upstream.**

- **`inflight-load-producer`** (`requestcontrol/dataproducer/inflightload/producer.go`): `PreRequest` adds the
  request's estimated **uncached prompt tokens** to a per-endpoint counter when the EPP dispatches it; they are
  released at the first response chunk (`StartOfStream`, prefill done), the request counter at `EndOfStream`. Per-request
  state is keyed by `x-request-id` and reaped by the plugin-state janitor after 5 min
  (`interface/plugin/plugin_state.go`: `stalenessThreshold = 5m`, `cleanupInterval = 1m`). Pods that leave the pool are
  cleaned via `EndpointExtractor`. Exposed for debugging through `StateDumper`.
- **`token-load-scorer`** (`scheduling/scorer/tokenload/token_load.go`): `score = 1 − min(1, tokens / queueThresholdTokens)`,
  `queueThresholdTokens` default **4 194 304** (128 requests × 32K). Category `Distribution`.
- `active-request-scorer` (same producer, request counts), `context-length-aware` (routes by prompt length to pods
  labelled with a length range — a size-based pool/pod routing, relates to #11), `latency-scorer` +
  `predicted-latency-producer` (XGBoost TTFT/TPOT predictor trained by sidecar servers; the chart has a
  `latencyPredictor` section; needs training + prediction server images), `latency-slo-admitter`,
  `slo-headroom-tier-filter`.

So the plan changes from "write a plugin" to "configure and evaluate `token-load-scorer`". A custom Go plugin
would duplicate it. Tasks 3-5 of the work order become: design the *configuration* (threshold, weight), measure it,
and write down where it falls short. Two limits of the upstream design are visible in the source and tested in P8:

1. The counters are **EPP-local and count only traffic this EPP dispatched** (`PreRequest`). Load that reaches a pod by
   another path (another EPP replica, a direct client, anything that bypasses the gateway) is invisible; the pod's own
   metrics (queue-scorer) are the only signal for it.
2. The default `queueThresholdTokens` is 4 Mi tokens, so at lab scale (a few thousand tokens in flight) the score
   moves by < 0.002: the scorer is a no-op until the threshold is sized to the backend.

### 3. Plugin interfaces, lifecycle, registration, build

`pkg/epp/framework/interface/`:

- `scheduling.Scorer` (`Score(ctx, *InferenceRequest, []Endpoint) map[Endpoint]float64`, `Category()`), `Filter`, `Picker`.
- `requestcontrol` (`interface/requestcontrol/plugins.go`): `PreRequest` (after scheduling, before dispatch),
  `ResponseHeaderProcessor`, `ResponseBodyProcessor` (called per streamed chunk; `EndOfStream` is the last call;
  the interface has no error/disconnect signal, upstream TODO `gateway-api-inference-extension#2079`),
  `DataProducer` (runs before filters/scorers), `Admitter`/`PreAdmitter`.
- Registration: `fwkplugin.Register(type, factory)` (`interface/plugin/registry.go`), `RegisterAsDefaultProducer` for
  producers that should be auto-created. In-tree plugins are registered by `Runner.registerInTreePlugins()`.
  Configuration: `EndpointPickerConfig` YAML (`apiVersion: llm-d.ai/v1alpha1`) with `plugins:` (type/name/parameters)
  and `schedulingProfiles:` (`pluginRef` + `weight`); the file is given by `--config-file`, in our chart by
  `router.epp.pluginsConfigFile` + `router.epp.pluginsCustomConfig` (a ConfigMap read only at startup).
- Out-of-tree build (not needed now): a custom `main` that calls `fwkplugin.Register(...)` and then
  `runner.NewRunner().Run(ctx)` (`cmd/epp/main.go` is exactly that with no extra registrations); `Runner` also has
  `WithSchedulerConfig`, `WithRequestControlConfig`, `WithCustomCollectors`. Upstream `Dockerfile.epp` builds
  `cmd/epp/main.go` with `golang:1.25.11`, `CGO_ENABLED=0`, distroless static base.

### 4. Tokenizer or raw body?

The EPP parses the body (`requesthandling/parsers/openai`, default parser) into `InferenceRequestBody`, and the
`token-producer` (`requestcontrol/dataproducer/tokenizer/`) puts a `TokenizedPrompt` on it. Backends: **`estimate`
(default, auto-created; ≈ 4 bytes per token, `bytesPerToken = 4` in `estimate.go`, token IDs not real)**, `vllm` (calls the
engine's `/v1/chat/completions/render`, plain HTTP), deprecated UDS sidecar. `inflight-load-producer` uses
`TokenizedPrompt.TokenCount()` (`token_estimator.go`), so with no tokenizer configured it counts bytes/4. The estimate
error against the simulator's own count is measured in P8 (GAPS.md).

Part 2 (design: threshold, weight, failure modes, alternatives) is appended after P8.
