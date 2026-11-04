# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T07:49:55.585-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 16 | 0 | 3,998 | 4,088 |
| 30 | high | 2 | 1 | 2 | 6 | 10 | 0 | 4,131 | 4,234 |
| 40 | high | 2 | 2 | 2 | 6 | 11 | 0 | 4,010 | 4,100 |
| 50 | high | 3 | 3 | 3 | 6 | 10 | 0 | 4,073 | 4,417 |
| 60 | high | 3 | 3 | 3 | 6 | 11 | 0 | 4,109 | 4,969 |
| 70 | high | 3 | 3 | 3 | 6 | 12 | 0 | 4,072 | 5,351 |
| 80 | high | 3 | 3 | 3 | 6 | 12 | 0 | 2,895 | 5,465 |
| 90 | high | 3 | 3 | 3 | 6 | 12 | 0 | 3,267 | 4,814 |
| 100 | high | 3 | 3 | 3 | 6 | 14 | 0 | 2,973 | 4,794 |
| 110 | high | 3 | 3 | 3 | 6 | 11 | 0 | 434 | 5,746 |
| 120 | high | 3 | 3 | 3 | 6 | 12 | 0 | 3,002 | 4,749 |
| 130 | high | 3 | 3 | 3 | 6 | 12 | 0 | 2,698 | 5,823 |
| 140 | high | 3 | 3 | 3 | 6 | 12 | 0 | 3,865 | 5,293 |
| 150 | high | 3 | 3 | 3 | 6 | 13 | 0 | 397 | 4,613 |
| 160 | high | 3 | 3 | 3 | 6 | 12 | 0 | 2,649 | 5,496 |
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

requests: 180 sent, 180 ok, 0 errors

events:

    {"t": "2026-11-03T07:49:55.129-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:50:15.129-05:00", "rel_s": 20.0, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:50:34.970-05:00", "rel_s": 39.84, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "3833m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T07:50:34.970-05:00", "rel_s": 39.84, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-89rsg", "created": "2026-11-03T12:50:34Z"}
    {"t": "2026-11-03T07:50:39.315-05:00", "rel_s": 44.19, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-89rsg"}
    {"t": "2026-11-03T07:50:48.904-05:00", "rel_s": 53.78, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-sxcq2", "created": "2026-11-03T12:50:48Z"}
    {"t": "2026-11-03T07:50:50.109-05:00", "rel_s": 54.98, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "2917m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T07:50:53.320-05:00", "rel_s": 58.19, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-sxcq2"}
    {"t": "2026-11-03T07:51:05.324-05:00", "rel_s": 70.2, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-89rsg"}
    {"t": "2026-11-03T07:51:06.039-05:00", "rel_s": 70.91, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-sxcq2"}
    {"t": "2026-11-03T07:52:48.466-05:00", "rel_s": 173.34, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:53:48.974-05:00", "rel_s": 233.85, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-89rsg"}
    {"t": "2026-11-03T07:53:50.023-05:00", "rel_s": 234.9, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T07:54:19.947-05:00", "rel_s": 264.82, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T07:54:19.948-05:00", "rel_s": 264.82, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-sxcq2"}
    {"t": "2026-11-03T07:54:40.579-05:00", "rel_s": 285.45, "event": "run_end", "phase": "idle2", "settled": true}
