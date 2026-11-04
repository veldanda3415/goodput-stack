# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T09:02:12.321-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 354 | 597 |
| 30 | high | 1 | 1 | 1 | 2 | 8 | 0 | 487 | 653 |
| 40 | high | 1 | 1 | 1 | 2 | 9 | 0 | 364 | 626 |
| 50 | high | 2 | 2 | 2 | 2 | 8 | 0 | 361 | 475 |
| 60 | high | 2 | 2 | 2 | 2 | 8 | 0 | 466 | 500 |
| 70 | high | 2 | 2 | 2 | 2 | 8 | 0 | 456 | 587 |
| 80 | high | 2 | 2 | 2 | 2 | 9 | 0 | 444 | 459 |
| 90 | high | 2 | 2 | 2 | 2 | 10 | 0 | 430 | 503 |
| 100 | high | 2 | 2 | 2 | 2 | 9 | 0 | 355 | 495 |
| 110 | high | 2 | 2 | 2 | 2 | 10 | 0 | 334 | 546 |
| 120 | high | 2 | 2 | 2 | 2 | 9 | 0 | 441 | 592 |
| 130 | high | 2 | 2 | 2 | 2 | 9 | 0 | 396 | 494 |
| 140 | high | 2 | 2 | 2 | 2 | 10 | 0 | 421 | 471 |
| 150 | high | 2 | 2 | 2 | 2 | 8 | 0 | 405 | 604 |
| 160 | high | 2 | 2 | 2 | 2 | 10 | 0 | 364 | 582 |
| 170 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 180 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 135 sent, 135 ok, 0 errors

events:

    {"t": "2026-11-03T09:02:11.418-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:02:31.438-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:03:04.217-05:00", "rel_s": 52.8, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 99, "averageValue": "3987m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:03:04.218-05:00", "rel_s": 52.8, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-4wpwk", "created": "2026-11-03T14:03:03Z"}
    {"t": "2026-11-03T09:03:08.320-05:00", "rel_s": 56.9, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-4wpwk"}
    {"t": "2026-11-03T09:03:08.323-05:00", "rel_s": 56.91, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-4wpwk"}
    {"t": "2026-11-03T09:05:02.319-05:00", "rel_s": 170.9, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:06:04.314-05:00", "rel_s": 232.9, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:06:04.315-05:00", "rel_s": 232.9, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-4wpwk"}
    {"t": "2026-11-03T09:06:24.397-05:00", "rel_s": 252.98, "event": "run_end", "phase": "idle2", "settled": true}
