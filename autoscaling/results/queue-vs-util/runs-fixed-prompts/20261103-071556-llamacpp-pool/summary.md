# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T07:15:56.550-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 16 | 0 | 4,024 | 4,069 |
| 30 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,156 | 4,496 |
| 40 | high | 2 | 2 | 2 | 6 | 9 | 0 | 4,411 | 5,285 |
| 50 | high | 2 | 2 | 2 | 6 | 13 | 0 | 2,950 | 5,251 |
| 60 | high | 2 | 2 | 2 | 6 | 15 | 0 | 2,307 | 3,913 |
| 70 | high | 2 | 2 | 2 | 6 | 11 | 0 | 1,118 | 4,416 |
| 80 | high | 2 | 2 | 2 | 6 | 17 | 0 | 1,421 | 3,286 |
| 90 | high | 3 | 3 | 3 | 6 | 12 | 0 | 748 | 5,762 |
| 100 | high | 3 | 3 | 3 | 6 | 14 | 0 | 459 | 3,270 |
| 110 | high | 3 | 3 | 3 | 6 | 17 | 0 | 487 | 2,378 |
| 120 | high | 3 | 3 | 3 | 6 | 14 | 0 | 726 | 2,917 |
| 130 | high | 3 | 3 | 3 | 6 | 14 | 0 | 3,034 | 5,296 |
| 140 | high | 3 | 3 | 3 | 6 | 11 | 0 | 429 | 2,562 |
| 150 | high | 3 | 3 | 3 | 6 | 16 | 0 | 480 | 2,726 |
| 160 | high | 3 | 3 | 3 | 6 | 15 | 0 | 509 | 2,731 |
| 170 | idle2 | 3 | 3 | 3 | 5 | 0 | 0 | - | - |
| 180 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 300 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 204 sent, 204 ok, 0 errors

events:

    {"t": "2026-11-03T07:15:56.058-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:16:16.061-05:00", "rel_s": 20.0, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:16:40.649-05:00", "rel_s": 44.59, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 70, "averageValue": "2829m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:16:40.649-05:00", "rel_s": 44.59, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-cd8ch", "created": "2026-11-03T12:16:40Z"}
    {"t": "2026-11-03T07:16:45.316-05:00", "rel_s": 49.26, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-cd8ch"}
    {"t": "2026-11-03T07:16:45.320-05:00", "rel_s": 49.26, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-cd8ch"}
    {"t": "2026-11-03T07:17:26.321-05:00", "rel_s": 90.26, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 92, "averageValue": "3684m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:17:26.323-05:00", "rel_s": 90.27, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-f4222", "created": "2026-11-03T12:17:25Z"}
    {"t": "2026-11-03T07:17:30.320-05:00", "rel_s": 94.26, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-f4222"}
    {"t": "2026-11-03T07:17:31.049-05:00", "rel_s": 94.99, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-f4222"}
    {"t": "2026-11-03T07:18:49.406-05:00", "rel_s": 173.35, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:20:11.315-05:00", "rel_s": 255.26, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:20:11.317-05:00", "rel_s": 255.26, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-cd8ch"}
    {"t": "2026-11-03T07:20:41.314-05:00", "rel_s": 285.26, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:20:41.315-05:00", "rel_s": 285.26, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-f4222"}
    {"t": "2026-11-03T07:21:01.528-05:00", "rel_s": 305.47, "event": "run_end", "phase": "idle2", "settled": true}
