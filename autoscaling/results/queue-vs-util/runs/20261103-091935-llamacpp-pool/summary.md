# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T09:19:36.321-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 14 | 0 | 4,392 | 4,418 |
| 30 | high | 2 | 1 | 2 | 6 | 10 | 0 | 4,622 | 5,741 |
| 40 | high | 2 | 2 | 2 | 6 | 10 | 0 | 878 | 3,284 |
| 50 | high | 3 | 3 | 3 | 6 | 12 | 0 | 931 | 3,585 |
| 60 | high | 3 | 3 | 3 | 6 | 16 | 0 | 604 | 3,638 |
| 70 | high | 3 | 3 | 3 | 6 | 13 | 0 | 609 | 2,057 |
| 80 | high | 3 | 3 | 3 | 6 | 14 | 0 | 893 | 3,577 |
| 90 | high | 3 | 3 | 3 | 6 | 14 | 0 | 991 | 2,382 |
| 100 | high | 3 | 3 | 3 | 6 | 14 | 0 | 986 | 3,971 |
| 110 | high | 3 | 3 | 3 | 6 | 12 | 0 | 646 | 2,830 |
| 120 | high | 3 | 3 | 3 | 6 | 16 | 0 | 792 | 2,560 |
| 130 | high | 3 | 3 | 3 | 6 | 15 | 0 | 613 | 2,670 |
| 140 | high | 3 | 3 | 3 | 6 | 12 | 0 | 844 | 3,316 |
| 150 | high | 3 | 3 | 3 | 6 | 15 | 0 | 826 | 3,290 |
| 160 | high | 3 | 3 | 3 | 6 | 12 | 0 | 625 | 2,273 |
| 170 | idle2 | 3 | 3 | 3 | 3 | 1 | 0 | 559 | 559 |
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

requests: 200 sent, 200 ok, 0 errors

events:

    {"t": "2026-11-03T09:19:35.717-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:19:55.734-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:20:13.320-05:00", "rel_s": 37.6, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "3"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:20:14.346-05:00", "rel_s": 38.63, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-98npd", "created": "2026-11-03T14:20:13Z"}
    {"t": "2026-11-03T09:20:16.363-05:00", "rel_s": 40.65, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-98npd"}
    {"t": "2026-11-03T09:20:17.370-05:00", "rel_s": 41.65, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-98npd"}
    {"t": "2026-11-03T09:20:28.592-05:00", "rel_s": 52.88, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "3750m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:20:28.592-05:00", "rel_s": 52.88, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-56tsb", "created": "2026-11-03T14:20:27Z"}
    {"t": "2026-11-03T09:20:32.010-05:00", "rel_s": 56.29, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-56tsb"}
    {"t": "2026-11-03T09:20:33.323-05:00", "rel_s": 57.61, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-56tsb"}
    {"t": "2026-11-03T09:22:28.624-05:00", "rel_s": 172.91, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:23:29.042-05:00", "rel_s": 233.33, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:23:29.044-05:00", "rel_s": 233.33, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-98npd"}
    {"t": "2026-11-03T09:23:59.313-05:00", "rel_s": 263.6, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:23:59.315-05:00", "rel_s": 263.6, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-56tsb"}
    {"t": "2026-11-03T09:24:19.723-05:00", "rel_s": 284.01, "event": "run_end", "phase": "idle2", "settled": true}
