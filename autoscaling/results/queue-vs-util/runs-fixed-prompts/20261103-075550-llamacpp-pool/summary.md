# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T07:55:51.300-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 16 | 0 | 3,990 | 4,071 |
| 30 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,067 | 4,216 |
| 40 | high | 3 | 3 | 3 | 6 | 10 | 0 | 4,034 | 4,571 |
| 50 | high | 3 | 3 | 3 | 6 | 10 | 0 | 4,006 | 4,042 |
| 60 | high | 3 | 3 | 3 | 6 | 11 | 0 | 3,992 | 5,269 |
| 70 | high | 3 | 3 | 3 | 6 | 12 | 0 | 2,957 | 5,401 |
| 80 | high | 3 | 3 | 3 | 6 | 13 | 0 | 3,295 | 4,617 |
| 90 | high | 3 | 3 | 3 | 6 | 13 | 0 | 392 | 5,636 |
| 100 | high | 3 | 3 | 3 | 6 | 13 | 0 | 3,576 | 5,543 |
| 110 | high | 3 | 3 | 3 | 6 | 11 | 0 | 367 | 5,784 |
| 120 | high | 3 | 3 | 3 | 6 | 13 | 0 | 3,089 | 3,549 |
| 130 | high | 3 | 3 | 3 | 6 | 14 | 0 | 3,146 | 5,479 |
| 140 | high | 3 | 3 | 3 | 6 | 10 | 0 | 2,693 | 4,931 |
| 150 | high | 3 | 3 | 3 | 6 | 15 | 0 | 536 | 3,592 |
| 160 | high | 3 | 3 | 3 | 6 | 14 | 0 | 3,223 | 5,020 |
| 170 | idle2 | 3 | 3 | 3 | 6 | 0 | 0 | - | - |
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
| 290 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 185 sent, 185 ok, 0 errors

events:

    {"t": "2026-11-03T07:55:50.679-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:56:10.698-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:56:35.539-05:00", "rel_s": 44.86, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "5"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T07:56:35.539-05:00", "rel_s": 44.86, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-5f75p", "created": "2026-11-03T12:56:34Z"}
    {"t": "2026-11-03T07:56:35.543-05:00", "rel_s": 44.86, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-nkw8c", "created": "2026-11-03T12:56:34Z"}
    {"t": "2026-11-03T07:56:38.317-05:00", "rel_s": 47.64, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-5f75p"}
    {"t": "2026-11-03T07:56:38.319-05:00", "rel_s": 47.64, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-nkw8c"}
    {"t": "2026-11-03T07:57:01.328-05:00", "rel_s": 70.65, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-nkw8c"}
    {"t": "2026-11-03T07:57:03.459-05:00", "rel_s": 72.78, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-5f75p"}
    {"t": "2026-11-03T07:58:44.508-05:00", "rel_s": 173.83, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:59:50.315-05:00", "rel_s": 239.64, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T07:59:50.317-05:00", "rel_s": 239.64, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-5f75p"}
    {"t": "2026-11-03T08:00:20.314-05:00", "rel_s": 269.64, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T08:00:20.315-05:00", "rel_s": 269.64, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-nkw8c"}
    {"t": "2026-11-03T08:00:40.614-05:00", "rel_s": 289.94, "event": "run_end", "phase": "idle2", "settled": true}
