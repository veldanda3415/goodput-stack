# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T08:39:48.321-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 341 | 578 |
| 30 | high | 1 | 1 | 1 | 2 | 10 | 0 | 414 | 580 |
| 40 | high | 1 | 1 | 1 | 2 | 10 | 0 | 423 | 569 |
| 50 | high | 1 | 1 | 1 | 2 | 10 | 0 | 433 | 574 |
| 60 | high | 1 | 1 | 1 | 2 | 10 | 0 | 449 | 666 |
| 70 | high | 1 | 1 | 1 | 2 | 8 | 0 | 447 | 664 |
| 80 | high | 1 | 1 | 1 | 2 | 10 | 0 | 318 | 485 |
| 90 | high | 1 | 1 | 1 | 2 | 11 | 0 | 317 | 336 |
| 100 | high | 1 | 1 | 1 | 2 | 10 | 0 | 310 | 342 |
| 110 | high | 1 | 1 | 1 | 2 | 9 | 0 | 310 | 346 |
| 120 | high | 1 | 1 | 1 | 2 | 10 | 0 | 317 | 340 |
| 130 | high | 1 | 1 | 1 | 2 | 11 | 0 | 317 | 347 |
| 140 | high | 1 | 1 | 1 | 2 | 9 | 0 | 332 | 334 |
| 150 | high | 1 | 1 | 1 | 2 | 10 | 0 | 321 | 346 |
| 160 | high | 1 | 1 | 1 | 2 | 11 | 0 | 321 | 341 |
| 170 | idle2 | 1 | 1 | 1 | 2 | 0 | 0 | - | - |
| 180 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 149 sent, 149 ok, 0 errors

events:

    {"t": "2026-11-03T08:39:47.720-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:40:07.738-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:42:39.399-05:00", "rel_s": 171.68, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:42:59.419-05:00", "rel_s": 191.7, "event": "run_end", "phase": "idle2", "settled": true}
