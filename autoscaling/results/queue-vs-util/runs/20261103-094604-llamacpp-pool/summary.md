# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T09:46:05.322-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 331 | 560 |
| 30 | high | 1 | 1 | 1 | 2 | 9 | 0 | 319 | 342 |
| 40 | high | 2 | 2 | 2 | 2 | 8 | 0 | 351 | 391 |
| 50 | high | 2 | 2 | 2 | 2 | 8 | 0 | 414 | 486 |
| 60 | high | 2 | 2 | 2 | 2 | 8 | 0 | 426 | 479 |
| 70 | high | 2 | 2 | 2 | 2 | 8 | 0 | 429 | 548 |
| 80 | high | 2 | 2 | 2 | 2 | 10 | 0 | 441 | 687 |
| 90 | high | 2 | 2 | 2 | 2 | 8 | 0 | 438 | 612 |
| 100 | high | 2 | 2 | 2 | 2 | 8 | 0 | 474 | 681 |
| 110 | high | 2 | 2 | 2 | 2 | 8 | 0 | 430 | 679 |
| 120 | high | 2 | 2 | 2 | 2 | 8 | 0 | 489 | 653 |
| 130 | high | 2 | 2 | 2 | 2 | 8 | 0 | 453 | 644 |
| 140 | high | 2 | 2 | 2 | 2 | 9 | 0 | 471 | 486 |
| 150 | high | 2 | 2 | 2 | 2 | 10 | 0 | 457 | 488 |
| 160 | high | 2 | 2 | 2 | 2 | 8 | 0 | 423 | 489 |
| 170 | idle2 | 2 | 2 | 2 | 1 | 0 | 0 | - | - |
| 180 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 128 sent, 128 ok, 0 errors

events:

    {"t": "2026-11-03T09:46:04.765-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:46:24.767-05:00", "rel_s": 20.0, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:46:49.430-05:00", "rel_s": 44.67, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 99, "averageValue": "3993m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:46:49.431-05:00", "rel_s": 44.67, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7zcf9", "created": "2026-11-03T14:46:49Z"}
    {"t": "2026-11-03T09:46:53.408-05:00", "rel_s": 48.64, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7zcf9"}
    {"t": "2026-11-03T09:46:58.408-05:00", "rel_s": 53.65, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7zcf9"}
    {"t": "2026-11-03T09:48:56.193-05:00", "rel_s": 171.43, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:50:04.933-05:00", "rel_s": 240.17, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "12m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:50:04.934-05:00", "rel_s": 240.17, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-7zcf9"}
    {"t": "2026-11-03T09:50:25.284-05:00", "rel_s": 260.52, "event": "run_end", "phase": "idle2", "settled": true}
