# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T08:15:15.268-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 15 | 0 | 4,365 | 4,401 |
| 30 | high | 1 | 1 | 1 | 6 | 9 | 0 | 4,578 | 4,654 |
| 40 | high | 2 | 2 | 2 | 6 | 9 | 0 | 4,871 | 5,986 |
| 50 | high | 2 | 2 | 2 | 6 | 13 | 0 | 1,875 | 3,409 |
| 60 | high | 2 | 2 | 2 | 6 | 13 | 0 | 1,984 | 3,397 |
| 70 | high | 2 | 2 | 2 | 6 | 12 | 0 | 2,017 | 2,835 |
| 80 | high | 2 | 2 | 3 | 6 | 14 | 0 | 2,033 | 3,411 |
| 90 | high | 3 | 3 | 3 | 6 | 12 | 0 | 750 | 2,341 |
| 100 | high | 3 | 3 | 3 | 6 | 14 | 0 | 835 | 4,464 |
| 110 | high | 3 | 3 | 3 | 6 | 15 | 0 | 595 | 2,281 |
| 120 | high | 3 | 3 | 3 | 6 | 13 | 0 | 611 | 3,081 |
| 130 | high | 3 | 3 | 3 | 6 | 14 | 0 | 610 | 3,272 |
| 140 | high | 3 | 3 | 3 | 6 | 13 | 0 | 1,162 | 3,561 |
| 150 | high | 3 | 3 | 3 | 6 | 14 | 0 | 644 | 3,515 |
| 160 | high | 3 | 3 | 3 | 6 | 13 | 0 | 607 | 2,634 |
| 170 | idle2 | 3 | 3 | 3 | 4 | 0 | 0 | - | - |
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

requests: 193 sent, 193 ok, 0 errors

events:

    {"t": "2026-11-03T08:15:14.724-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:15:34.742-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:15:59.316-05:00", "rel_s": 44.59, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 58, "averageValue": "2329m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:15:59.317-05:00", "rel_s": 44.59, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-d7ww2", "created": "2026-11-03T13:15:59Z"}
    {"t": "2026-11-03T08:16:03.455-05:00", "rel_s": 48.73, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-d7ww2"}
    {"t": "2026-11-03T08:16:03.456-05:00", "rel_s": 48.73, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-d7ww2"}
    {"t": "2026-11-03T08:16:44.203-05:00", "rel_s": 89.48, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 98, "averageValue": "3957m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:16:44.207-05:00", "rel_s": 89.48, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-tv5cm", "created": "2026-11-03T13:16:43Z"}
    {"t": "2026-11-03T08:16:47.337-05:00", "rel_s": 92.61, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-tv5cm"}
    {"t": "2026-11-03T08:16:47.338-05:00", "rel_s": 92.61, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-tv5cm"}
    {"t": "2026-11-03T08:18:07.780-05:00", "rel_s": 173.06, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:19:29.329-05:00", "rel_s": 254.61, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "11m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:19:29.332-05:00", "rel_s": 254.61, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-d7ww2"}
    {"t": "2026-11-03T08:19:59.313-05:00", "rel_s": 284.59, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:19:59.314-05:00", "rel_s": 284.59, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-tv5cm"}
    {"t": "2026-11-03T08:20:20.905-05:00", "rel_s": 306.18, "event": "run_end", "phase": "idle2", "settled": true}
