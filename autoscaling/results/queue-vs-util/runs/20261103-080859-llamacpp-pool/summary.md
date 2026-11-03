# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T08:09:00.322-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 14 | 0 | 4,345 | 4,430 |
| 30 | high | 1 | 1 | 1 | 6 | 11 | 0 | 4,443 | 4,524 |
| 40 | high | 2 | 2 | 2 | 6 | 8 | 0 | 4,706 | 5,812 |
| 50 | high | 2 | 2 | 2 | 6 | 14 | 0 | 1,964 | 3,414 |
| 60 | high | 2 | 2 | 2 | 6 | 13 | 0 | 1,516 | 2,975 |
| 70 | high | 2 | 2 | 2 | 6 | 13 | 0 | 1,898 | 3,476 |
| 80 | high | 3 | 2 | 3 | 6 | 13 | 0 | 1,626 | 3,001 |
| 90 | high | 3 | 3 | 3 | 6 | 14 | 0 | 1,208 | 2,745 |
| 100 | high | 3 | 3 | 3 | 6 | 16 | 0 | 627 | 2,255 |
| 110 | high | 3 | 3 | 3 | 6 | 12 | 0 | 814 | 3,752 |
| 120 | high | 3 | 3 | 3 | 6 | 16 | 0 | 793 | 3,218 |
| 130 | high | 3 | 3 | 3 | 6 | 14 | 0 | 690 | 2,983 |
| 140 | high | 3 | 3 | 3 | 6 | 12 | 0 | 666 | 2,205 |
| 150 | high | 3 | 3 | 3 | 6 | 14 | 0 | 719 | 3,823 |
| 160 | high | 3 | 3 | 3 | 6 | 16 | 0 | 823 | 2,641 |
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

requests: 200 sent, 200 ok, 0 errors

events:

    {"t": "2026-11-03T08:08:59.407-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:09:19.426-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:09:44.088-05:00", "rel_s": 44.68, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 56, "averageValue": "2252m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:09:44.088-05:00", "rel_s": 44.68, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-8grd6", "created": "2026-11-03T13:09:43Z"}
    {"t": "2026-11-03T08:09:47.124-05:00", "rel_s": 47.72, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-8grd6"}
    {"t": "2026-11-03T08:09:47.125-05:00", "rel_s": 47.72, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-8grd6"}
    {"t": "2026-11-03T08:10:29.291-05:00", "rel_s": 89.89, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 98, "averageValue": "3951m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:10:29.291-05:00", "rel_s": 89.89, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-6mlbb", "created": "2026-11-03T13:10:28Z"}
    {"t": "2026-11-03T08:10:32.319-05:00", "rel_s": 92.91, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-6mlbb"}
    {"t": "2026-11-03T08:10:33.274-05:00", "rel_s": 93.87, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-6mlbb"}
    {"t": "2026-11-03T08:11:52.915-05:00", "rel_s": 173.51, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:13:14.208-05:00", "rel_s": 254.8, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:13:14.211-05:00", "rel_s": 254.81, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-6mlbb"}
    {"t": "2026-11-03T08:13:44.314-05:00", "rel_s": 284.91, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:13:44.315-05:00", "rel_s": 284.91, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-8grd6"}
    {"t": "2026-11-03T08:14:05.040-05:00", "rel_s": 305.63, "event": "run_end", "phase": "idle2", "settled": true}
