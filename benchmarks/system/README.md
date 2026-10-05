# benchmarks/system/ - end-to-end benchmarks (planned)

**Scope:** client -> router (`router/`) -> backends deployed by `deploy/` on Kubernetes, with
autoscaling. Measures what users experience: TTFT/ITL against the SLO, goodput, queueing
under bursts, scale-up lag, cost per request.

Will reuse `../harness/` (streaming client, stats, storage, provenance). Differences from
`../engine/`: no server lifecycle (the cluster is the system under test), OpenAI
`/v1/chat/completions` instead of llama.cpp `/completion`, and open-loop arrival rates
instead of only closed-loop concurrency.
