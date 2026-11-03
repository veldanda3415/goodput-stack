# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T09:29:50.971-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 351 | 592 |
| 30 | high | 1 | 1 | 1 | 2 | 8 | 0 | 320 | 326 |
| 40 | high | 1 | 1 | 1 | 2 | 9 | 0 | 337 | 358 |
| 50 | high | 1 | 1 | 1 | 2 | 9 | 0 | 345 | 389 |
| 60 | high | 1 | 1 | 1 | 2 | 8 | 0 | 342 | 377 |
| 70 | high | 1 | 1 | 1 | 2 | 9 | 0 | 355 | 363 |
| 80 | high | 1 | 1 | 1 | 2 | 8 | 0 | 366 | 420 |
| 90 | high | 1 | 1 | 1 | 2 | 9 | 0 | 351 | 363 |
| 100 | high | 1 | 1 | 1 | 2 | 8 | 0 | 330 | 386 |
| 110 | high | 1 | 1 | 1 | 2 | 9 | 0 | 349 | 378 |
| 120 | high | 1 | 1 | 1 | 2 | 10 | 0 | 342 | 375 |
| 130 | high | 1 | 1 | 1 | 2 | 8 | 0 | 351 | 363 |
| 140 | high | 1 | 1 | 1 | 2 | 9 | 0 | 341 | 367 |
| 150 | high | 1 | 1 | 1 | 2 | 9 | 0 | 325 | 382 |
| 160 | high | 1 | 1 | 1 | 2 | 8 | 0 | 351 | 375 |
| 170 | idle2 | 1 | 1 | 1 | 1 | 0 | 0 | - | - |
| 180 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 131 sent, 131 ok, 0 errors

events:

    {"t": "2026-11-03T09:29:50.445-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:30:10.465-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:32:41.365-05:00", "rel_s": 170.92, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:33:01.386-05:00", "rel_s": 190.94, "event": "run_end", "phase": "idle2", "settled": true}
