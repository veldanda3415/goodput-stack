# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T09:40:03.325-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 14 | 0 | 4,303 | 4,954 |
| 30 | high | 1 | 1 | 1 | 6 | 9 | 0 | 4,971 | 5,098 |
| 40 | high | 2 | 1 | 2 | 6 | 8 | 0 | 5,863 | 6,449 |
| 50 | high | 2 | 2 | 2 | 6 | 10 | 0 | 1,471 | 4,102 |
| 60 | high | 2 | 2 | 2 | 6 | 12 | 0 | 2,197 | 3,436 |
| 70 | high | 3 | 2 | 3 | 6 | 12 | 0 | 2,223 | 3,785 |
| 80 | high | 3 | 3 | 3 | 6 | 11 | 0 | 619 | 3,366 |
| 90 | high | 3 | 3 | 3 | 6 | 13 | 0 | 1,809 | 3,063 |
| 100 | high | 3 | 3 | 3 | 6 | 14 | 0 | 659 | 3,382 |
| 110 | high | 3 | 3 | 3 | 6 | 12 | 0 | 644 | 3,656 |
| 120 | high | 3 | 3 | 3 | 6 | 15 | 0 | 615 | 2,072 |
| 130 | high | 3 | 3 | 3 | 6 | 13 | 0 | 637 | 3,543 |
| 140 | high | 3 | 3 | 3 | 6 | 14 | 0 | 1,051 | 2,293 |
| 150 | high | 3 | 3 | 3 | 6 | 14 | 0 | 815 | 3,184 |
| 160 | high | 3 | 3 | 3 | 6 | 13 | 0 | 640 | 3,343 |
| 170 | idle2 | 3 | 3 | 3 | 4 | 0 | 0 | - | - |
| 180 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 184 sent, 184 ok, 0 errors

events:

    {"t": "2026-11-03T09:40:02.668-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:40:22.686-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:40:49.254-05:00", "rel_s": 46.59, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 99, "averageValue": "3995m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:40:50.321-05:00", "rel_s": 47.65, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-nv4xw", "created": "2026-11-03T14:40:49Z"}
    {"t": "2026-11-03T09:40:54.319-05:00", "rel_s": 51.65, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-nv4xw"}
    {"t": "2026-11-03T09:40:54.321-05:00", "rel_s": 51.65, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-nv4xw"}
    {"t": "2026-11-03T09:41:19.256-05:00", "rel_s": 76.59, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 98, "averageValue": "3944m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:41:19.257-05:00", "rel_s": 76.59, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-925l4", "created": "2026-11-03T14:41:18Z"}
    {"t": "2026-11-03T09:41:23.922-05:00", "rel_s": 81.25, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-925l4"}
    {"t": "2026-11-03T09:41:26.327-05:00", "rel_s": 83.66, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-925l4"}
    {"t": "2026-11-03T09:42:55.349-05:00", "rel_s": 172.68, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:44:04.316-05:00", "rel_s": 241.65, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:44:04.318-05:00", "rel_s": 241.65, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-925l4"}
    {"t": "2026-11-03T09:44:34.152-05:00", "rel_s": 271.48, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "12m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:44:34.153-05:00", "rel_s": 271.49, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-nv4xw"}
    {"t": "2026-11-03T09:44:55.470-05:00", "rel_s": 292.8, "event": "run_end", "phase": "idle2", "settled": true}
