# benchmarks/engine/ - direct engine benchmarks

**Scope:** client -> one inference server, directly. No router, no Kubernetes, no autoscaling.
Use these to characterise a backend/model/quantization in isolation (and to re-test after
changing a model, e.g. a fine-tune). Numbers here are an upper bound on what the full
system can deliver, not what users see - that's `../system/`.

## Running

Config-driven: one YAML defines defaults, experiments and sweeps. For every sweep point
the harness starts a **fresh** `llama-server`, waits for `/health`, drives streaming load,
samples `/metrics`, `/slots` and server RSS, stops the server and writes results.

```bash
make venv                                                         # once: .venv with httpx + PyYAML
make bench-engine-list                                            # experiments in configs/llamacpp.yaml
make bench-engine-dry EXP=slot_limit                              # show sweep points + exact server commands
make bench-engine EXP=smoke                                       # ~10 s sanity check
make bench-engine EXP=ttft
make bench-engine EXP=slot_limit ARGS="--set client.requests=8 --set server.threads=4"
make bench-engine EXP=ctx_tradeoff ARGS="--keep"                  # never prune this run's raw files
```

`--set key=value` overrides any dotted config key; overriding a swept key pins it to one value.

| Experiment | Sweeps | Look at |
|---|---|---|
| `slot_limit` | `-np` × concurrency | `ttft_ms_p50/p95` step-up, `m_deferred_max` |
| `ctx_tradeoff` | `-c` | `kv_buffer_mib` (theory ≈ 12 KiB/token), `rss_peak_mib`, `itl_ms_p50` |
| `ttft` | prompt tokens | `ttft_ms_*` vs `srv_prompt_ms_*`; `ttft_minus_srv_prompt_ms` = HTTP + queue + 1st decode |
| `metrics_semantics` | scrape interval | gauge vs counter-derived rates, `m_gauge_zero_windows`, idle probe |
| `mem_bandwidth` | threads (llama-bench) | `effective_bw_gb_s` vs `memcopy_1thread_gb_s` in manifest |

Measurement notes:
- Prompts are calibrated to an exact token count with `/tokenize`, carry a unique prefix,
  and are sent with `cache_prompt: false`; `-cram 0` disables the host-RAM prompt cache.
- `ignore_eos: true` makes every request decode exactly `max_tokens`.
- TTFT is client-side: the first streamed token chunk after the request was sent.
- `probe_memory: true` adds a short extra start at `-lv 4` to read KV/model/compute
  buffer sizes (the default verbosity hides them; `-lv 4` during load is too noisy).

## Results and storage

```
results/engine/<YYYYmmdd-HHMMSS>_<experiment>/
  manifest.json          system, llama.cpp commit, model hash, resolved config   committed
  summary.csv            one row per sweep point                                  committed
  <point>/summary.json   per-point summary                                        committed
  <point>/requests.jsonl, metrics.jsonl, server.log.gz, probe.log.gz, bench.jsonl  git-ignored
```

- Server logs are drained by the harness, capped at `storage.max_log_mib` (head plus the last
  2000 lines), then gzipped.
- After each run, raw files from all but the newest `storage.keep_raw_runs` runs of that
  experiment are deleted. Summaries are never deleted. A `.keep` file in a run directory
  (`--keep`) exempts it. Prune manually with `make bench-engine-prune EXP=...`; check size with `make bench-du`.
- WSL2: deleting files frees space inside Linux, but the Windows-side `ext4.vhdx` does not
  shrink by itself (compact it with `wsl --manage <distro> --set-sparse true` or `Optimize-VHD`).
  Don't point `results_dir` at `/tmp` - it is tmpfs (RAM) here.
- `guards.min_free_ram_mib` skips a point if MemAvailable is too low (e.g. a huge `-c`).
