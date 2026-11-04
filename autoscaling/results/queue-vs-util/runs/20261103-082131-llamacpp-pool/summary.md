# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T08:21:32.281-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 322 | 564 |
| 30 | high | 1 | 1 | 1 | 2 | 10 | 0 | 418 | 568 |
| 40 | high | 1 | 1 | 1 | 2 | 10 | 0 | 429 | 590 |
| 50 | high | 2 | 1 | 2 | 2 | 10 | 0 | 460 | 614 |
| 60 | high | 2 | 2 | 2 | 2 | 10 | 0 | 431 | 472 |
| 70 | high | 2 | 2 | 2 | 2 | 8 | 0 | 414 | 461 |
| 80 | high | 2 | 2 | 2 | 2 | 10 | 0 | 379 | 462 |
| 90 | high | 2 | 2 | 2 | 2 | 9 | 0 | 387 | 431 |
| 100 | high | 2 | 2 | 2 | 2 | 9 | 0 | 335 | 476 |
| 110 | high | 2 | 2 | 2 | 2 | 11 | 0 | 416 | 551 |
| 120 | high | 2 | 2 | 2 | 2 | 10 | 0 | 397 | 449 |
| 130 | high | 2 | 2 | 2 | 2 | 9 | 0 | 325 | 469 |
| 140 | high | 2 | 2 | 2 | 2 | 9 | 0 | 341 | 446 |
| 150 | high | 2 | 2 | 2 | 2 | 11 | 0 | 327 | 476 |
| 160 | high | 2 | 2 | 2 | 2 | 10 | 0 | 344 | 589 |
| 170 | idle2 | 2 | 2 | 2 | 2 | 0 | 0 | - | - |
| 180 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 146 sent, 146 ok, 0 errors

events:

    {"t": "2026-11-03T08:21:31.816-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:21:51.833-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:22:29.391-05:00", "rel_s": 57.58, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4003m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:22:29.391-05:00", "rel_s": 57.58, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fggz8", "created": "2026-11-03T13:22:29Z"}
    {"t": "2026-11-03T08:22:32.432-05:00", "rel_s": 60.62, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fggz8"}
    {"t": "2026-11-03T08:22:33.543-05:00", "rel_s": 61.73, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fggz8"}
    {"t": "2026-11-03T08:24:23.752-05:00", "rel_s": 171.94, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:25:44.811-05:00", "rel_s": 253.0, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:25:44.812-05:00", "rel_s": 253.0, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-fggz8"}
    {"t": "2026-11-03T08:26:04.850-05:00", "rel_s": 273.03, "event": "run_end", "phase": "idle2", "settled": true}
