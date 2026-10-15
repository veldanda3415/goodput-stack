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


## Part 2: Design (configure the upstream scorer)

Decision: do **not** write a scorer. Enable upstream `inflight-load-producer` + `token-load-scorer` on sim-pool's EPP
through a values switch (`deploy/gateway/epp-sim-token-load.values.yaml`, `make epp-plugin-on/off`). The Go plugin, module,
unit tests and EPP image from the original plan are not built: they would duplicate code that ships in the pinned binary.

**What is tracked.** Per endpoint, outstanding prompt tokens dispatched by this EPP replica (and a request counter).
Incremented in `PreRequest` (after the pick), the tokens released at the first response chunk (`StartOfStream`, i.e.
prefill done), the request counter at `EndOfStream`. Keyed by `x-request-id`.

**Token estimate.** Default `token-producer` `estimate` backend = bytes/4. Against the simulator's own count (words + ~5)
the EPP estimate with our probe prompts ("w<i>" words) was about 20% high; real English text is closer to 4 bytes/token
but varies by tokenizer and language, so treat the estimate as +-25% and the threshold as an order-of-magnitude knob. The
`vllm` render backend gives real counts at the cost of an extra HTTP call per request; not enabled.

**Normalisation and weight.** `score = 1 - min(1, tokens / queueThresholdTokens)`, 0..1 like the other scorers. The upstream
default threshold (4,194,304) makes the scorer a no-op at lab scale, so we set 8192 (= sim max-num-seqs 2 x max-model-len
4096: the most prompt work one pod can hold). Weight 4 against queue 2, kv 2, prefix 3: queue-scorer is min-max over
waiting count only, so its maximum swing is 2; the token scorer's swing between a pod with ~7k queued prompt tokens and
one with ~1k is about 0.9 x 4 = 3.6, enough to overrule queue depth when work is very unequal, while for similar
token loads it is near zero and the queue/prefix scorers decide as before. The weight was not tuned beyond P8 + P1.

**Failure modes.**
- EPP restart: counters reset to 0; requests in flight at restart are never decremented (the process is gone), so the
  scorer is blind to them until they finish and new ones are counted.
- Several EPP replicas: state is per replica. Each replica sees only the traffic it dispatched, so with N replicas each
  under-counts by up to (N-1)/N. We run 1 replica per pool. Load sent straight to pods is invisible too (P8 `on-direct`).
- Client disconnect (#19 / P3): `ResponseBodyProcessor` has no disconnect signal. Tokens are released at the first chunk,
  so a disconnect after first token leaks nothing; one before it, or a stream that never produces a chunk, is held until
  the plugin-state janitor reaps it (`stalenessThreshold` 5 min, `cleanupInterval` 1 min,
  `interface/plugin/plugin_state.go`). A leaked entry therefore biases scoring for at most ~5 min. This is the TTL.
- Backend that never completes: same TTL.

**Alternatives.**
- Size-based pool routing (#11): needs a router in the path or client cooperation and static size classes; the scorer
  works at the existing EPP hook with no new component.
- Chunked prefill: an engine-side mitigation that lowers the cost of mixing long and short prompts on one pod; does not
  place requests. Complementary, not evaluated (the simulator has no such model).
- P/D disaggregation: removes the problem by separating prefill; needs GPUs and KV transfer, out of reach for a CPU lab.
- Upstream latency predictor (`latency-scorer` + `predicted-latency-producer`): the principled fix but needs training and
  prediction sidecars and real latency data; not worth it for a simulator. Re-evaluate on the T4.
- Custom scorer: rejected, duplicates upstream.
