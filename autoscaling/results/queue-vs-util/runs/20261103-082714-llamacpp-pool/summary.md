# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T08:27:14.880-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 14 | 0 | 4,333 | 4,352 |
| 30 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,453 | 4,473 |
| 40 | high | 1 | 1 | 1 | 6 | 11 | 0 | 4,519 | 4,654 |
| 50 | high | 1 | 1 | 1 | 6 | 9 | 0 | 4,591 | 4,731 |
| 60 | high | 2 | 2 | 2 | 6 | 9 | 0 | 2,695 | 5,883 |
| 70 | high | 2 | 2 | 2 | 6 | 15 | 0 | 1,371 | 3,092 |
| 80 | high | 2 | 2 | 2 | 6 | 14 | 0 | 2,035 | 2,867 |
| 90 | high | 2 | 2 | 2 | 6 | 13 | 0 | 2,424 | 3,193 |
| 100 | high | 3 | 2 | 3 | 6 | 13 | 0 | 1,749 | 4,048 |
| 110 | high | 3 | 3 | 3 | 6 | 11 | 0 | 620 | 2,818 |
| 120 | high | 3 | 3 | 3 | 6 | 14 | 0 | 754 | 3,015 |
| 130 | high | 3 | 3 | 3 | 6 | 15 | 0 | 618 | 2,290 |
| 140 | high | 3 | 3 | 3 | 6 | 14 | 0 | 801 | 3,813 |
| 150 | high | 3 | 3 | 3 | 6 | 14 | 0 | 616 | 1,367 |
| 160 | high | 3 | 3 | 3 | 6 | 13 | 0 | 780 | 3,936 |
| 170 | idle2 | 3 | 3 | 3 | 6 | 0 | 0 | - | - |
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

requests: 189 sent, 189 ok, 0 errors

events:

    {"t": "2026-11-03T08:27:14.409-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:27:34.430-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:28:15.315-05:00", "rel_s": 60.91, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4004m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:28:16.294-05:00", "rel_s": 61.89, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-z6wv9", "created": "2026-11-03T13:28:15Z"}
    {"t": "2026-11-03T08:28:19.211-05:00", "rel_s": 64.8, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-z6wv9"}
    {"t": "2026-11-03T08:28:19.212-05:00", "rel_s": 64.8, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-z6wv9"}
    {"t": "2026-11-03T08:29:00.322-05:00", "rel_s": 105.91, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 98, "averageValue": "3958m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:29:00.322-05:00", "rel_s": 105.91, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-995t4", "created": "2026-11-03T13:28:59Z"}
    {"t": "2026-11-03T08:29:04.488-05:00", "rel_s": 110.08, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-995t4"}
    {"t": "2026-11-03T08:29:04.490-05:00", "rel_s": 110.08, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-995t4"}
    {"t": "2026-11-03T08:30:07.201-05:00", "rel_s": 172.79, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:31:30.316-05:00", "rel_s": 255.91, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:31:30.318-05:00", "rel_s": 255.91, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-z6wv9"}
    {"t": "2026-11-03T08:32:00.314-05:00", "rel_s": 285.91, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:32:00.315-05:00", "rel_s": 285.91, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-995t4"}
    {"t": "2026-11-03T08:32:22.334-05:00", "rel_s": 307.93, "event": "run_end", "phase": "idle2", "settled": true}
