# scripts/

Small helpers. **Week 1.**

| Script | What it does |
|---|---|
| `stream_client.py` | Real TTFT / ITL from an OpenAI-compatible stream (`/v1/chat/completions`). Separates the role-only first chunk from the first content chunk, and prints the engine's `prompt_ms` next to TTFT. `stream_chat()` is importable for the Week 5 system benchmarks. Needs `httpx` (`make venv`). |
| `queue_probe.py` | N concurrent streams + `/metrics` sampling: client TTFT vs engine `prompt_ms` under queueing (stdlib only). |

```bash
kubectl -n inference port-forward svc/inf-llamacpp 18080:8080 &
.venv/bin/python scripts/stream_client.py                      # one request
.venv/bin/python scripts/stream_client.py --runs 5             # + p50/p95 summary
.venv/bin/python scripts/stream_client.py --prompt-file p.txt --max-tokens 32 --json
```

Port-forward is fine for engine measurements, but it adds a hop through the kube API server.
The first request on a new tunnel pays ~30 ms extra, so use `--runs` and read the p50.
