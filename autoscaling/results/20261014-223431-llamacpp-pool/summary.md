# loadgen llamacpp-pool

`autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300`  started 2026-10-14T22:34:32.450-04:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 15 | 0 | 3,600 | 4,393 |
| 30 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,347 | 4,420 |
| 40 | high | 3 | 1 | 3 | 6 | 9 | 0 | 4,612 | 6,488 |
| 50 | high | 3 | 3 | 3 | 6 | 12 | 0 | 572 | 2,770 |
| 60 | high | 3 | 3 | 3 | 6 | 12 | 0 | 643 | 3,801 |
| 70 | high | 3 | 3 | 3 | 6 | 13 | 0 | 695 | 2,336 |
| 80 | high | 3 | 3 | 3 | 6 | 17 | 0 | 634 | 2,754 |
| 90 | high | 3 | 3 | 3 | 6 | 12 | 0 | 611 | 3,045 |
| 100 | high | 3 | 3 | 3 | 6 | 17 | 0 | 794 | 3,340 |
| 110 | high | 3 | 3 | 3 | 6 | 16 | 0 | 727 | 3,092 |
| 120 | high | 3 | 3 | 3 | 6 | 14 | 0 | 838 | 3,259 |
| 130 | high | 3 | 3 | 3 | 6 | 16 | 0 | 799 | 4,682 |
| 140 | high | 3 | 3 | 3 | 6 | 13 | 0 | 572 | 3,009 |
| 150 | high | 3 | 3 | 3 | 6 | 14 | 0 | 815 | 2,742 |
| 160 | high | 3 | 3 | 3 | 6 | 16 | 0 | 572 | 2,792 |
| 170 | idle2 | 3 | 3 | 3 | 6 | 0 | 0 | - | - |
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

requests: 206 sent, 206 ok, 0 errors

events:

    {"t": "2026-10-14T22:34:31.878-04:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-10-14T22:34:51.898-04:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-10-14T22:35:19.513-04:00", "rel_s": 47.64, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "4667m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:35:19.514-04:00", "rel_s": 47.64, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-87pmp", "created": "2026-10-15T02:35:18Z"}
    {"t": "2026-10-14T22:35:19.515-04:00", "rel_s": 47.64, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dcnqd", "created": "2026-10-15T02:35:18Z"}
    {"t": "2026-10-14T22:35:21.415-04:00", "rel_s": 49.54, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-87pmp"}
    {"t": "2026-10-14T22:35:21.422-04:00", "rel_s": 49.55, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dcnqd"}
    {"t": "2026-10-14T22:35:22.499-04:00", "rel_s": 50.62, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-87pmp"}
    {"t": "2026-10-14T22:35:24.657-04:00", "rel_s": 52.78, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dcnqd"}
    {"t": "2026-10-14T22:37:25.079-04:00", "rel_s": 173.2, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-10-14T22:38:34.611-04:00", "rel_s": 242.73, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:38:34.613-04:00", "rel_s": 242.74, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-dcnqd"}
    {"t": "2026-10-14T22:39:04.609-04:00", "rel_s": 272.73, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:39:04.610-04:00", "rel_s": 272.73, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-87pmp"}
    {"t": "2026-10-14T22:39:25.195-04:00", "rel_s": 293.32, "event": "run_end", "phase": "idle2", "settled": true}
