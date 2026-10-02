# scripts/

Small client-side probes that run against a llama.cpp server (usually via port-forward). **Week 1.**

| Script | Question it answers | Load shape | Deps |
|---|---|---|---|
| [`stream_client.py`](stream_client.py) | What is the real TTFT / ITL a user sees, and how does it compare to the engine's `prompt_ms`? | 1..N streams, each sending `--runs` requests back to back, staggered starts | `httpx` (`make venv`) |
| [`queue_probe.py`](queue_probe.py) | When more requests arrive than the server has slots, who waits and for how long? | one burst: N requests fired at the same instant, one each | stdlib only |
| [`bringup_timing.sh`](bringup_timing.sh) | After a chart change: how long until a new pod is serving, warm vs cold, and is there downtime? | restarts/deletes/scales the deployment; a prober pod hits the Service every ~0.1 s | kubectl, helm, curl, python3 |

```bash
kubectl -n inference port-forward svc/inf-llamacpp 18080:8080 &
.venv/bin/python scripts/stream_client.py                      # one request
.venv/bin/python scripts/stream_client.py --runs 5             # + p50/p95 summary
.venv/bin/python scripts/stream_client.py -np 4 --runs 3       # 4 parallel streams
python3 scripts/queue_probe.py --url http://127.0.0.1:18080 --n 4 --max-tokens 64
```

Port-forward is fine for engine measurements, but it adds a hop through the kube API server.
The first request on a new tunnel pays ~30 ms extra, so use `--runs` and read the p50.
Port-forward also bypasses the NetworkPolicy (it enters the pod's own network namespace), so it
says nothing about in-cluster reachability; test that from a pod (see `helm test`).

## stream_client.py

- `POST /v1/chat/completions` with `stream: true`, `stream_options.include_usage`, `cache_prompt: false`.
- TTFB = first SSE chunk of any kind; **TTFT = first chunk whose `delta.content` is non-empty**
  (the role-only chunk doesn't count); ITL = gaps between content chunks.
- Reads llama.cpp `timings` (`prompt_n`, `prompt_ms`, `cache_n`, `predicted_per_token_ms`) and `usage`
  from the final chunks. Prints `TTFT - prompt_ms` (HTTP + queueing + first decode).
- `--parallel/-np N` (client streams, not server slots), `--runs`, `--stagger`; polls `/metrics`
  for peak `requests_processing` / `requests_deferred`; `--json` = one line per request.
- `stream_chat()` is importable (async) and returns a dict per request; reuse it instead of re-parsing SSE.

## queue_probe.py

What it does, step by step:

1. Starts a background thread that polls `GET /metrics` every 0.5 s and records
   `llamacpp:requests_processing` and `llamacpp:requests_deferred` (needs `--metrics` on the server;
   errors are recorded, not fatal).
2. Starts `--n` threads at once. Each sends one streaming `POST /v1/chat/completions`
   (`max_tokens`, `cache_prompt: false`) with a **unique prompt** (request index + a nanosecond
   nonce), so no request can reuse another's KV cache.
3. Per request it records client TTFT (first chunk with non-empty `delta.content`), end-to-end
   time, number of content chunks, and the engine's `timings.prompt_ms` and
   `predicted_per_token_ms` from the final chunk.
4. Prints one row per request, **sorted by TTFT**, then the peak processing/deferred counts.

Columns: `client TTFT ms` · `engine prompt_ms` · **`gap ms` = TTFT − prompt_ms** (time queued before a
slot, plus network) · `e2e ms` · `tok` (content chunks) · `ms/tok` (engine decode time per token).

Example (pod with `-np 2`, 4 requests, 64 tokens, 2026-10-02):

```
req  client TTFT ms  engine prompt_ms    gap ms    e2e ms  tok  ms/tok
  2           558.2             535.9      22.3    2160.0   64    25.4
  3           559.4             537.7      21.8    2159.9   64    25.4
  0          2655.9             492.4    2163.5    4212.2   64    24.7
  1          2656.4             493.4    2162.9    4212.3   64    24.7

peak requests_processing=2  peak requests_deferred=2  (9 metric samples)
```

How to read it: the first `-np` requests get a slot (gap ≈ 20 ms). The rest wait in
`requests_deferred` for a whole generation to finish (gap ≈ the first wave's e2e, ~2.2 s here). The engine's
`prompt_ms` never shows that wait, only the client's TTFT does. Two prompts processed together also
share the CPU, so each one's `prompt_ms` is ~3× the single-request value (536 vs ~170 ms).

Limits (by design, it is a probe, not a benchmark): one burst with no stagger or repeats; no ITL or
percentiles; default `--url` is `:8080` (pass the port-forward URL); a request that errors raises
in its thread and is missing from the table; prompt length isn't controlled.
For repeatable numbers use `stream_client.py --parallel` or `benchmarks/engine/`.

## bringup_timing.sh

Run it **on demand after `helm upgrade`** (it only measures; it never changes chart values).

```bash
make bringup                                         # warm, rollout restart, 3 runs (median)
make bringup ARGS="--trigger delete --runs 2"        # pod deleted: is there an outage?
make bringup ARGS="--trigger scale"                  # scale 0 -> 1 (scale-from-zero, warm)
sudo -v && make bringup ARGS="--mode cold-cache"     # model evicted from page cache (needs sudo)
make bringup ARGS="--mode cold-model --yes"          # model deleted from PVC -> re-download (~470 MB)
```

| Mode | Not cached at start | Trigger | Real-world case |
|---|---|---|---|
| `warm` | nothing | restart / delete / scale | rollout, crash, scale-from-zero on a warm node |
| `cold-cache` | model pages in RAM | scale (forced) | node reboot; model evicted under memory pressure |
| `cold-model` | model file on the PVC | scale (forced) | first install, new model/quant, new node (local-path PVCs don't move) |

Cold modes force `scale`: llama.cpp mmaps the model and mapped pages can't be evicted while the old
pod runs. `cold-model` deletes the file with a helper pod after scale-to-0 (the server mounts `/models`
read-only). The freshly downloaded file is still in the page cache, so its *load* is warm.

What it records per run (seconds after the trigger): pod created/scheduled, init duration and action
(skip/download), container started (Kubernetes, 1 s, rounded down so it can read slightly negative),
**model loaded** (server log, ms), **Ready** and **endpoint ready** (polled ~0.5 s), **serving** (first 200
through the Service after an outage, else the new endpoint), startup-probe failures, non-200 count and
**downtime** from the prober. Output: `benchmarks/results/bringup/<ts>_<mode>_<trigger>/REPORT.md`,
raw `run-N/`, and one line per series in `benchmarks/results/bringup/history.jsonl` (chart revision,
image, values hash, git commit) to compare across chart changes.

Failure handling: preflight (context, deployment rolled out, 1 replica, sudo for cold-cache, confirm
for cold-model) exits 2; fail fast on ImagePull/CrashLoop/restarts/init error/unscheduled > 30 s;
on failure a `diagnostics/` bundle is saved, the series stops, exit 1, no rollback. A trap always
removes the prober pod and never leaves the deployment at 0 replicas.

First results (2026-10-02, chart rev 15, warm node, `startupProbe.periodSeconds 1`, readiness 5 s):

| | restart (2 runs) | delete (2 runs) | scale 0→1 | cold-model |
|---|---:|---:|---:|---:|
| model load (server log) | 0.67 s | 0.66 s | 0.68 s | 0.64 s |
| time to serving | 3.97 s | 3.8 s | 3.79 s | **71.3 s** (65 s download) |
| Ready − model loaded | 2.8 s | 2.8 s | 1.6 s | 1.9 s |
| non-200 via Service | 0 | **0** | 7 (no pod existed) | 129 |

Readings: the model loads in < 1 s, so a warm bring-up is mostly **probe and controller lag** (the
readiness probe still runs every 5 s, so up to ~3 s is wasted after load). `delete` causes no errors
because the old pod keeps serving during its `preStop` sleep and kube-proxy falls back to
terminating endpoints. After an endpoint turns ready it takes ~0.7 s more before kube-proxy routes
to it. A cold node is dominated by the model download.

## Writing another probe

Conventions both scripts follow; keep them so numbers stay comparable:

- **Time on the client** with a monotonic clock (`time.perf_counter()`), from just before the
  request is sent.
- **TTFT = first non-empty `delta.content`**, never the first byte or chunk. With a router or vLLM
  in front, the role-only chunk can arrive long before any text.
- **Defeat caching**: `cache_prompt: false` and/or a unique nonce in each prompt; check `timings.cache_n == 0`.
- **Pair client time with engine time**: read `timings` from the final chunk, report
  `TTFT − prompt_ms` to split queueing/network from compute.
- **Watch the server while loading it**: sample `/metrics` (`requests_processing`,
  `requests_deferred`) in parallel; report peaks.
- **Count tokens from the stream** (content chunks) and cross-check with `usage.completion_tokens`
  (it is one higher when the end-of-sequence token produces no text).
- **Avoid lockstep** when sending more than one request per client: stagger starts, or results reflect
  synchronized collisions rather than steady load.
- Reuse `stream_client.stream_chat()` for the request/parsing part rather than re-implementing SSE
  handling. If a probe grows into a sweep with repeats and reports, it belongs in `benchmarks/`.
