# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T09:25:29.939-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 439 | 602 |
| 30 | high | 1 | 1 | 1 | 2 | 8 | 0 | 459 | 620 |
| 40 | high | 1 | 1 | 1 | 2 | 8 | 0 | 457 | 648 |
| 50 | high | 1 | 1 | 1 | 2 | 8 | 0 | 500 | 678 |
| 60 | high | 1 | 1 | 1 | 2 | 10 | 0 | 528 | 748 |
| 70 | high | 1 | 1 | 1 | 2 | 8 | 0 | 479 | 684 |
| 80 | high | 1 | 1 | 1 | 2 | 8 | 0 | 475 | 642 |
| 90 | high | 1 | 1 | 1 | 2 | 8 | 0 | 577 | 787 |
| 100 | high | 1 | 1 | 1 | 2 | 10 | 0 | 491 | 651 |
| 110 | high | 1 | 1 | 1 | 2 | 8 | 0 | 494 | 652 |
| 120 | high | 1 | 1 | 1 | 2 | 8 | 0 | 486 | 668 |
| 130 | high | 1 | 1 | 1 | 2 | 10 | 0 | 485 | 670 |
| 140 | high | 1 | 1 | 1 | 2 | 8 | 0 | 514 | 696 |
| 150 | high | 1 | 1 | 1 | 2 | 8 | 0 | 490 | 654 |
| 160 | high | 1 | 1 | 1 | 2 | 8 | 0 | 502 | 678 |
| 170 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 180 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 128 sent, 128 ok, 0 errors

events:

    {"t": "2026-11-03T09:25:29.414-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:25:49.434-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:28:19.673-05:00", "rel_s": 170.26, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:28:39.692-05:00", "rel_s": 190.28, "event": "run_end", "phase": "idle2", "settled": true}
