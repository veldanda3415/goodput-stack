# benchmarks/engine/ — direct engine benchmarks

**Scope:** client → one inference server, directly. No router, no Kubernetes, no autoscaling.
Use this suite to characterise a backend / model / quantization on its own, and to re-test
after changing any of them (new quant, fine-tune, llama.cpp upgrade, different machine).
Numbers here are an **upper bound** for the full system, not what users see — that is
[`../system/`](../system/).

- [Quick start](#quick-start)
- [How a run works](#how-a-run-works)
- [What can be measured](#what-can-be-measured)
- [Experiments](#experiments)
- [Parameters and their impact](#parameters-and-their-impact)
- [Overriding and adding experiments](#overriding-and-adding-experiments)
- [Try these](#try-these)
- [Simulator target (vLLM sim in k3s)](#simulator-target-vllm-sim-in-k3s)
- [Caveats](#caveats)
- [Results and storage](#results-and-storage)

---

## Quick start

```bash
make venv                                   # once: .venv with httpx + PyYAML
make bench-engine-list                      # list experiments
make bench-engine-dry EXP=saturation        # show sweep points + exact llama-server commands (nothing runs)
make bench-engine EXP=smoke                 # ~10 s sanity check
make bench-engine EXP=saturation            # a real experiment (~30 min)
make bench-engine-all                       # every experiment back to back (~1.5 h) + one index page
make bench-engine-all ARGS="--skip saturation --skip ttft_load"   # shorter batch
```

`bench-engine-all` runs the `batch:` list from the YAML in order (quick experiments first),
keeps going if one fails, and writes `results/engine/<timestamp>_ALL.md`: status, duration and
link per experiment plus each one's derived findings. Ctrl-C stops the batch and keeps partial results.

Stop any `llama-server` you started by hand first — the harness refuses to start if the port
(8080) is taken. Don't run two experiments at once; they share the CPU and skew each other.

Without make: `.venv/bin/python -m benchmarks.engine.run <experiment> [--set key=value ...]`.

Every run prints a table and writes `benchmarks/results/engine/<timestamp>_<experiment>/REPORT.md`
— **open that first.**

## How a run works

```
configs/llamacpp.yaml
  defaults ─► experiment overrides ─► --set overrides ─► sweep (cartesian product of points)

for each point (× repeats):
  1. start a FRESH llama-server with the point's flags      (no cache/slot state carried over)
  2. wait for /health; record startup time and idle RSS
  3. build prompts of an exact token count via /tokenize   (unique prefix per request)
  4. warmup requests (discarded)
  5. N closed-loop clients stream requests; per token timestamps recorded
     meanwhile: /metrics + /slots sampled every scrape_interval_s, RSS every 0.25 s
  6. idle probe (2 scrapes, 1 s apart), stop the server, gzip its log
  7. summarise → summary.json; append to summary.csv
end: REPORT.md (curated table + derived findings), prune raw files of old runs
```

Code: [run.py](run.py) (runner), [server.py](server.py) (lifecycle), [bench.py](bench.py)
(llama-bench), shared [../harness/](../harness/) (client, stats, report, storage, sysinfo).

## What can be measured

All latencies are measured **client-side** unless marked "server".

| Metric (summary key) | Meaning | Why it matters |
|---|---|---|
| **TTFT** `ttft_ms_*` | request sent → first generated token received | "how long until it starts answering"; dominated by prefill + queueing |
| **server prefill** `srv_prompt_ms_*` | server's own prompt-processing time (`timings.prompt_ms`) | isolates compute from HTTP/queueing |
| **TTFT − prefill** `ttft_minus_srv_prompt_ms_*` | HTTP + waiting for a slot/batch + first decode step | grows when requests queue or collide |
| **TPOT** `tpot_ms_*` | per request: (last token − first token) / (tokens − 1) | per-user generation speed (1000/TPOT = tok/s one user sees) |
| **ITL** `itl_ms_*` | every gap between consecutive tokens, all requests pooled | shows stalls/spikes; noisier than TPOT |
| **E2E** `e2e_ms_*` | request sent → stream finished | total request time |
| **total output** `agg_output_tok_s` | all output tokens / wall time of the run | server throughput incl. ramp-up and drain |
| **steady output** `steady_output_tok_s` | tokens emitted while *every* client was busy / that window | throughput at the intended concurrency — prefer this |
| **SLO met** `slo_attainment_pct` | % of requests with TTFT ≤ `slo.ttft_ms` **and** TPOT ≤ `slo.tpot_ms` | the user-facing verdict |
| **goodput** `goodput_tok_s` | output tokens of SLO-meeting requests / wall time | throughput that actually counts |
| **KV cache / weights / compute buf** `*_buffer_mib` | llama.cpp buffer sizes (needs `probe_memory`) | memory cost of context and model |
| **RSS** `rss_after_load_mib`, `rss_peak_mib` | server resident memory idle / peak | real memory footprint |
| **max queued** `m_deferred_max` | peak `requests_deferred` from /metrics | requests waiting because all slots were busy |
| **/metrics gauges vs counters** `m_*` | gauge `predicted_tokens_seconds` vs rates derived from counters | what the server's own metrics really report |
| **decode tok/s, bandwidth** `gen_tok_s`, `effective_bw_gb_s` | llama-bench decode speed × model bytes | how close decode is to the memory-bandwidth limit |

Percentiles: every distribution has `_mean`, `_p50`, `_p95`, `_p99`, `_max`. With `repeats > 1`,
each value is the **median across repeats**, and headline metrics get `*_spread_pct`
((max − min) / median) — above ~10 % treat the result as a range.

## Experiments

Defined in [configs/llamacpp.yaml](configs/llamacpp.yaml). Each has a `report:` block that
chooses the table columns, a reading guide, and derived findings.

| Experiment | Question | Sweeps | Runtime | Read in REPORT.md |
|---|---|---|---|---|
| `smoke` | does the harness work? | — | 10 s | everything `ok` |
| `ttft` | how does TTFT grow with prompt length, one user, no queueing? | prompt 16…4096 tok | ~3 min | derived **prefill rate** and `TTFT ≈ a + b × tokens` |
| `ttft_load` | how does TTFT degrade with concurrent users? | prompt 128/512/2048 × clients 1/2/4/8 (4 slots) | ~10 min | prefill slowing (sharing CPU) vs "TTFT − prefill" (waiting for a slot) |
| `slot_limit` | what happens when clients > slots? | slots 1/2/4 × clients 1/2/4/8 | ~10 min | TTFT step-up + `max queued` once clients > slots |
| `saturation` | where does adding users stop paying off? optimum? | clients 1…24 (16 slots), 3 repeats | ~30 min | **knee**, max throughput, **SLO optimum**, scaling efficiency |
| `ctx_tradeoff` | what does a bigger `-c` cost? | ctx 512…32768 | ~5 min | derived **KiB/token** of KV (theory 12 KiB) and RSS growth |
| `metrics_semantics` | what do `/metrics` gauges average over? | scrape interval 0.5/2/5 s | ~5 min | gauge vs per-slot vs wall-clock rates; zero windows; idle reading |
| `mem_bandwidth` | is decode memory-bandwidth bound? | threads 1…16 (llama-bench) | ~3 min | best **GB/s** vs memcpy reference |

### Findings so far (real, CPU)

`saturation`, 2026-09-30, i7-10700 (8C/16T), WSL2, llama.cpp `7fe450e19`,
Qwen2.5-0.5B-Instruct Q4_K_M, 16 slots, 256-token prompts, 96–160 output tokens, 3 repeats
(spread ≤ 1.3 %), SLO TTFT ≤ 2 s and TPOT ≤ 50 ms:

| clients | TPOT p50 | TTFT p50 / p95 | steady tok/s | SLO met |
|---:|---:|---:|---:|---:|
| 1 | 15.9 ms | 0.64 / 0.68 s | 48 | 100 % |
| 2 | 30.0 ms | 0.68 / 0.72 s | 58 | 100 % |
| 4 | 50.7 ms | 0.71 / 1.15 s | 70 | 46 % |
| 8 | 94.6 ms | 0.77 / 2.15 s | 80 | 6 % |
| 16 | 157.4 ms | 0.84 / 7.85 s | 92 | 0 % |
| 24 | 163.7 ms | 11.8 / 19.8 s | 92 | 0 % (8 queued) |

- On this CPU batching buys little: 1 → 2 clients gives +22 % throughput but ~2× TPOT.
- **Operating point under this SLO: 2 concurrent requests per server** (~55 tok/s goodput).
- Clients > slots (24 > 16) → queueing, TTFT explodes.
- The first run without desynchronisation (clients in lockstep) overstated TTFT p50 by up to 8×
  and understated TPOT — see [Caveats](#caveats).

## Parameters and their impact

Set in YAML (`defaults:` or per experiment) or on the command line with `--set`.

### Server (`server.*`) — changes the system under test

| Key | Flag | Default | Impact on results |
|---|---|---|---|
| `model_path` / `hf_repo` | `-m` / `-hf` | Qwen2.5-0.5B Q4_K_M | Everything. Bigger model or higher-precision quant → slower decode (more bytes per token), more memory. |
| `ctx_size` | `-c` | 4096 | **Total** KV context. Split across slots (`ctx/parallel` each) unless `kv_unified`. Costs memory (~12 KiB/token here), barely speed. Too small → long prompts are rejected/truncated. |
| `parallel` | `-np` | 1 | Slots = requests processed at once. More slots → more batching (throughput) but slower per user; clients > slots → queueing (`max queued` > 0). |
| `threads` | `-t` | 8 | CPU threads. Decode scales until memory bandwidth saturates; >8 uses hyperthreads and often hurts. Prefill is compute-bound and scales better. |
| `kv_unified` | `-kvu` / `-no-kvu` | llama.cpp default | `true`: one shared KV pool (a slot can use more than `ctx/parallel`). `false`: fixed per-slot share. |
| `cache_ram_mib` | `-cram` | 0 (off) | Host-RAM prompt cache. Keep 0 for clean TTFT/memory numbers; enable to study cache reuse. |
| `probe_memory` | — | false | Extra short start at `-lv 4` to read KV/weights/compute buffer sizes (~2 s per point). |
| `log_verbosity` | `-lv` | null | Debug only; `-lv 4` during load produces huge logs and slows the server. |
| `extra_args` | anything | `--metrics --slots --no-webui` | Any other llama-server flag, e.g. `-fa on`, `-b`, `-ub`. Keep `--metrics --slots`. |

### Client (`client.*`) — changes the workload

| Key | Default | Impact on results |
|---|---|---|
| `prompt_tokens` | 256 | Exact input length. Drives TTFT (prefill ≈ linear in tokens) and KV use. |
| `max_tokens` | 128 | Output length. Longer → requests last longer, more overlap between clients; TPOT itself barely changes. |
| `max_tokens_jitter` | 0 | e.g. `0.25` → each request 0.75–1.25 × `max_tokens`. Breaks lockstep (see caveats). |
| `ignore_eos` | true | Forces the full output length so every request does the same work. `false` = model decides (variable, realistic, noisier). |
| `concurrency` | 1 | Closed-loop clients: each sends its next request as soon as the previous finishes. This is the load knob. |
| `requests` / `requests_per_client` / `min_requests` | 20 / null / 0 | Sample size. p95 needs ≥ ~20 samples; more → tighter percentiles, longer run. |
| `start_jitter_s` | 0 | Each client starts after a random 0…N s delay. Use ≈ one request's duration when concurrency > 1. |
| `cache_prompt` | false | `true` lets the server reuse KV across requests; prompts have unique prefixes, so there is little to reuse anyway. |
| `warmup` | 2 | Discarded requests before measuring (first-request effects: page faults, graph build). |
| `temperature` | 0.0 | Sampling; negligible effect on speed. |

### Run-level

| Key | Default | Impact |
|---|---|---|
| `repeats` | 1 | Runs each point N times on fresh servers → median + spread. Use 3 for anything you'll quote. |
| `slo.ttft_ms`, `slo.tpot_ms` | null | Enables SLO met % and goodput. **Your** latency targets — results depend entirely on them. |
| `metrics.scrape_interval_s` | 1.0 | /metrics sampling period; also changes what the gauges report (they reset on every scrape). 0 disables. |
| `guards.min_free_ram_mib` | 4096 | Skips a point instead of letting a huge `-c` push the machine into swap. |
| `storage.*` | see [below](#results-and-storage) | Log cap and retention. |

## Overriding and adding experiments

```bash
# scalar: set one value (pins a swept key to that value)
make bench-engine EXP=saturation ARGS="--set server.threads=4 --set repeats=1"

# list: replace or add a sweep axis
make bench-engine EXP=saturation ARGS='--set "client.concurrency=[1,2,4]"'

# list-valued key (extra_args): wrap in [[...]]; quote on/off/yes/no (YAML reads bare on as true)
make bench-engine EXP=ttft ARGS="--set \"server.extra_args=[[--metrics, --slots, --no-webui, -fa, 'on']]\""

# always check what will run first
make bench-engine-dry EXP=saturation ARGS='--set "server.threads=[4,8]"'
```

Several sweep axes are combined as a cartesian product (2 × 3 = 6 points). Derived findings such as
the saturation knee assume one main axis; for two axes read the table, or run the experiment once per value.

To add an experiment, append a block under `experiments:` in [configs/llamacpp.yaml](configs/llamacpp.yaml):

```yaml
  my_experiment:
    description: One line - what question this answers.
    server: {parallel: 4}                     # overrides of defaults
    client: {prompt_tokens: 512, requests: 20}
    sweep:
      client.concurrency: [1, 2, 4]
    report:
      columns: [ttft_ms_p50, tpot_ms_p50, steady_output_tok_s]
      look_for: What you expect to see and why.
      derive: [saturation]                    # optional: prefill_rate, kv_per_token, queueing, saturation, bandwidth, metrics_semantics
```

## Try these

Each one answers a question. Write your prediction down **before** running, then compare.

1. **Hyperthreads: help or hurt?**
   `make bench-engine EXP=saturation ARGS='--set "server.threads=[4,8,16]" --set "client.concurrency=[1,4]" --set repeats=1'`
   Expect decode (TPOT at 1 client) to improve 4 → 8 and flatten or worsen at 16, since decode is
   limited by memory bandwidth, not compute. Cross-check with `EXP=mem_bandwidth`.

2. **Reproduce the lockstep artifact.**
   `make bench-engine EXP=saturation ARGS='--set client.start_jitter_s=0 --set client.max_tokens_jitter=0 --set "client.concurrency=[4,8]" --set repeats=1'`
   Compare TTFT p50 and TPOT with the jittered run in *Findings so far*. Which of the two
   numbers would you have trusted?

3. **Long prompts change the knee.**
   `make bench-engine EXP=saturation ARGS='--set client.prompt_tokens=1024 --set "client.concurrency=[1,2,4,8]" --set repeats=1'`
   Prefill is compute-bound on CPU and competes with everyone's decode. Expect TTFT to fail the
   SLO earlier and the optimum to drop to 1 client. Useful for routing: route long prompts differently (#11).

4. **Does a looser SLO move the operating point?**
   `make bench-engine EXP=saturation ARGS='--set slo.tpot_ms=100 --set slo.ttft_ms=3000 --set "client.concurrency=[1,2,4,8]" --set repeats=1'`
   SLO checks happen per request at run time, so a new target needs a new run. Compare the
   "SLO optimum" line with the 50 ms / 2 s result (2 clients). How many more users does a
   2× looser TPOT buy?

5. **Slots vs clients.**
   `make bench-engine EXP=saturation ARGS='--set server.parallel=2 --set "client.concurrency=[1,2,4,8]" --set repeats=1'`
   With 2 slots, clients 4 and 8 queue. Compare TTFT p95 and throughput against 16 slots:
   is it better to queue requests or to batch them?

6. **Per-slot context limit and unified KV.**
   `make bench-engine EXP=smoke ARGS="--set server.parallel=4 --set server.ctx_size=4096 --set client.prompt_tokens=2000 --set server.kv_unified=false"`
   Each slot gets 4096 / 4 = 1024 cells, so every 2000-token request fails: the table shows
   **ok reqs = 0** and `default/requests.jsonl` holds the server's HTTP 400 *"request (2000 tokens)
   exceeds the available context size (1024 tokens)"*. Re-run with `--set server.kv_unified=true`:
   one shared pool lets a single slot use it, and the requests succeed (~5.4 s prefill here).
   Lesson for routing: with a per-slot split, max prompt length is `ctx / parallel`, not `ctx`.

7. **Flash attention.**
   `make bench-engine EXP=ttft ARGS="--set \"server.extra_args=[[--metrics, --slots, --no-webui, -fa, 'on']]\""`
   vs `'off'`. On CPU the effect on prefill is usually small; check the derived prefill rate.

8. **Prefill batch size.**
   `make bench-engine EXP=ttft ARGS="--set \"server.extra_args=[[--metrics, --slots, --no-webui, -ub, 128]]\""`
   (default `-ub` is 512). Smaller micro-batches → prefill in more steps → higher TTFT for long prompts.

9. **Another quantization.** Download e.g. the Q8_0 GGUF of the same model, then
   `make bench-engine EXP=saturation ARGS="--set server.model_path=/path/to/q8_0.gguf --set repeats=1"`.
   Expect roughly (Q8 bytes / Q4 bytes) slower decode if memory-bound — check against `mem_bandwidth`.

10. **Predict the /metrics gauge.** Before running `EXP=metrics_semantics`, write down what
    `predicted_tokens_seconds` will read at 0.5 s vs 5 s scrape intervals with 2 clients. The
    report shows gauge vs per-slot vs wall-clock rates and how many windows read 0.

## Simulator target (vLLM sim in k3s)

The same runner drives the chart's **vLLM simulator** ([deploy/README.md](../../deploy/README.md#vllm-simulator-sim-in-valuesyaml))
with [configs/sim.yaml](configs/sim.yaml): same experiment names, results in `results/sim/`,
every report stamped **SIMULATED**. Use it to check the measurement path (client, Service,
metrics) and the queueing model, and to see where a calibrated linear model departs from the
real engine. It does not measure engine speed.

```bash
make bench-sim-list
make bench-sim EXP=smoke                    # ~15 s
make bench-sim EXP=ttft                     # ~2 min
make bench-sim-all                          # smoke, ttft, slot_limit, ttft_load, saturation
make bench-compare A=benchmarks/results/engine/<ts>_ttft B=benchmarks/results/sim/<ts>_ttft
```

Differences from the llama.cpp target (`server.runtime: k8s`, `client.api: openai`):

| | llama.cpp (local) | simulator (k8s) |
|---|---|---|
| fresh server per point | new `llama-server` process | `kubectl rollout restart`, wait until the old pods are gone and the Service answers `/health/ready` 3× |
| server knobs per experiment / sweep | CLI flags | `server.sim: {flag: value}` and sweep keys `server.sim.<flag>`: patched into the ConfigMap for the run, **restored at the end** (also on Ctrl-C) |
| request | `POST /completion`, `n_predict` | `POST /v1/completions`, `model`, `max_tokens`, `stream_options.include_usage` |
| prompt of N tokens | `/tokenize` + `/detokenize` | vLLM `/tokenize` count, word prefix fitted to N (dummy tokenizer ≈ 1 token/word) |
| server-side timing | `timings.prompt_ms` per request | `vllm:*` histogram means over the measured requests (`m_srv_ttft_ms_mean`, `m_srv_queue_ms_mean`, ...) |
| queue / running | `requests_deferred` / `requests_processing` | `num_requests_waiting` / `num_requests_running` (same `m_deferred_max` / `m_processing_max` columns) |
| path | 127.0.0.1 | Service ClusterIP from the k3s host (kube-proxy, no tunnel); `server.base_url` for a port-forward elsewhere |
| provenance | llama.cpp commit, model sha | image digest, helm revision, ConfigMap config, and the config the pod **logged** at start (`<point>/target.json`) |

Extra columns: `ttft_minus_srv_ttft_ms_mean` (client TTFT − server TTFT = HTTP + Service hop,
~3–6 ms here; the simulator's TTFT histogram starts when a request leaves the queue, so when requests queue this gap also holds the queue wait — compare `m_srv_queue_ms_mean`), `usage_token_mismatch` (streamed chunks vs server `completion_tokens`, must be 0).
The `sim_model` derive prints measured TTFT/TPOT next to what the configured latency model
predicts, including the simulator's load-factor quirk (prefill counts the other running
requests, decode includes itself). A gap there is a measurement problem, not an engine finding.

First result (2026-10-02, `ttft`, 1 client): the simulator matches llama.cpp within 5 % at 128–512
prompt tokens and is 14 % / 24 % faster at 2048 / 4096 (llama.cpp prefill is super-linear on CPU,
and its decode slows with context: TPOT 24 ms at 4096 vs a flat 15 ms in the sim).

## Caveats

- **Lockstep.** With fixed lengths and a simultaneous start, closed-loop clients finish and resubmit
  together, so every prefill collides and nobody's decode is interrupted. That inflates TTFT and
  deflates TPOT. `start_jitter_s` + `max_tokens_jitter` break it; `steady_output_tok_s` excludes ramp/drain.
- **Closed loop ≠ real traffic.** Load backs off when the server slows (a client waits for its answer).
  Real users arrive regardless → queues can grow without bound. Open-loop arrival rates belong in `../system/`.
- **Prompt cache off.** Unique prefixes + `cache_prompt: false` + `-cram 0` → every TTFT is a cold prefill.
  Real chat traffic with shared system prompts will see lower TTFT.
- **Same machine.** The Python client shares the CPU with the server (small but non-zero). Keep
  `threads` ≤ physical cores. WSL2 and CPU frequency scaling add noise → use `repeats: 3` for numbers you quote.
- **ITL vs TPOT.** httpx may deliver streamed chunks in bursts, so single ITL gaps are noisy; TPOT
  (per-request mean) is the reliable per-user speed.
- **Scope.** CPU numbers do not transfer to the T4; the method and curve shapes do.

## Results and storage

```
results/engine/<YYYYmmdd-HHMMSS>_<experiment>/
  REPORT.md              readable summary: settings, curated table, derived findings  committed
  manifest.json          system, llama.cpp commit, model hash, resolved config       committed
  summary.csv            one row per sweep point, every metric (pandas/notebooks)     committed
  <point>/summary.json   per-point summary (+ memory log lines)                       committed
  <point>/rep-N/         per-repeat outputs when repeats > 1
  <point>/requests.jsonl, metrics.jsonl, server.log.gz, probe.log.gz, bench.jsonl      git-ignored
```

- Rebuild a report (e.g. after changing report code): `python -m benchmarks.engine.run --report <run_dir>`.
- Server logs are drained by the harness, capped at `storage.max_log_mib` (head plus the last
  2000 lines), then gzipped.
- After each run, raw files from all but the newest `storage.keep_raw_runs` runs of that
  experiment are deleted. Summaries are never deleted. `--keep` (a `.keep` file in the run
  directory) exempts a run. Prune manually with `make bench-engine-prune EXP=...`; check size with `make bench-du`.
- WSL2: deleting files frees space inside Linux, but the Windows-side `ext4.vhdx` does not
  shrink by itself (compact with `wsl --manage <distro> --set-sparse true` or `Optimize-VHD`).
  Don't point `results_dir` at `/tmp` — it is tmpfs (RAM) here.
