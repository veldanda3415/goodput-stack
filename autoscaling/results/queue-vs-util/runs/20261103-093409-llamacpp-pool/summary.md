# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T09:34:10.046-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 334 | 383 |
| 30 | high | 2 | 1 | 2 | 2 | 9 | 0 | 320 | 353 |
| 40 | high | 2 | 2 | 2 | 2 | 10 | 0 | 393 | 618 |
| 50 | high | 2 | 2 | 2 | 2 | 7 | 0 | 477 | 591 |
| 60 | high | 2 | 2 | 3 | 2 | 8 | 0 | 499 | 546 |
| 70 | high | 3 | 3 | 3 | 2 | 8 | 0 | 467 | 533 |
| 80 | high | 3 | 3 | 3 | 2 | 8 | 0 | 386 | 502 |
| 90 | high | 3 | 3 | 3 | 2 | 7 | 0 | 484 | 494 |
| 100 | high | 3 | 3 | 3 | 2 | 8 | 0 | 443 | 562 |
| 110 | high | 3 | 3 | 3 | 2 | 8 | 0 | 491 | 538 |
| 120 | high | 3 | 3 | 3 | 2 | 7 | 0 | 488 | 569 |
| 130 | high | 3 | 3 | 3 | 2 | 7 | 0 | 458 | 473 |
| 140 | high | 3 | 3 | 3 | 2 | 9 | 0 | 475 | 593 |
| 150 | high | 3 | 3 | 3 | 2 | 8 | 0 | 479 | 494 |
| 160 | high | 3 | 3 | 3 | 2 | 8 | 0 | 482 | 498 |
| 170 | idle2 | 3 | 3 | 3 | 2 | 0 | 0 | - | - |
| 180 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 122 sent, 122 ok, 0 errors

events:

    {"t": "2026-11-03T09:34:09.510-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:34:29.530-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:34:49.319-05:00", "rel_s": 39.81, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 77, "averageValue": "3102m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:34:49.321-05:00", "rel_s": 39.81, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-wkrtq", "created": "2026-11-03T14:34:48Z"}
    {"t": "2026-11-03T09:34:52.353-05:00", "rel_s": 42.84, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-wkrtq"}
    {"t": "2026-11-03T09:34:52.355-05:00", "rel_s": 42.85, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-wkrtq"}
    {"t": "2026-11-03T09:35:18.678-05:00", "rel_s": 69.17, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 90, "averageValue": "3617m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:35:18.679-05:00", "rel_s": 69.17, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-5fm9z", "created": "2026-11-03T14:35:18Z"}
    {"t": "2026-11-03T09:35:22.323-05:00", "rel_s": 72.81, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-5fm9z"}
    {"t": "2026-11-03T09:35:29.323-05:00", "rel_s": 79.81, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-5fm9z"}
    {"t": "2026-11-03T09:37:00.916-05:00", "rel_s": 171.41, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:38:04.317-05:00", "rel_s": 234.81, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "12m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:38:04.319-05:00", "rel_s": 234.81, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-5fm9z"}
    {"t": "2026-11-03T09:38:33.866-05:00", "rel_s": 264.36, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "12m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:38:33.867-05:00", "rel_s": 264.36, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-wkrtq"}
    {"t": "2026-11-03T09:38:54.024-05:00", "rel_s": 284.52, "event": "run_end", "phase": "idle2", "settled": true}
