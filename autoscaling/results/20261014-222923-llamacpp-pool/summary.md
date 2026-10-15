# loadgen llamacpp-pool

`autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300`  started 2026-10-14T22:29:24.618-04:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 3 | 3 | 3 | 6 | 13 | 0 | 2,095 | 6,386 |
| 30 | high | 3 | 3 | 3 | 6 | 15 | 0 | 602 | 2,134 |
| 40 | high | 3 | 3 | 3 | 6 | 11 | 0 | 684 | 3,470 |
| 50 | high | 3 | 3 | 3 | 6 | 14 | 0 | 1,381 | 3,545 |
| 60 | high | 3 | 3 | 3 | 6 | 12 | 0 | 847 | 3,429 |
| 70 | high | 3 | 3 | 3 | 6 | 11 | 0 | 1,106 | 3,345 |
| 80 | high | 3 | 3 | 3 | 6 | 14 | 0 | 997 | 3,758 |
| 90 | high | 3 | 3 | 3 | 6 | 10 | 0 | 724 | 5,541 |
| 100 | high | 4 | 3 | 4 | 6 | 12 | 0 | 699 | 3,693 |
| 110 | high | 4 | 3 | 4 | 6 | 16 | 0 | 634 | 2,914 |
| 120 | high | 4 | 3 | 4 | 6 | 15 | 0 | 574 | 2,484 |
| 130 | high | 4 | 3 | 4 | 6 | 14 | 0 | 984 | 2,912 |
| 140 | high | 4 | 3 | 4 | 6 | 14 | 0 | 641 | 2,345 |
| 150 | high | 4 | 3 | 4 | 6 | 15 | 0 | 611 | 2,856 |
| 160 | high | 3 | 3 | 3 | 6 | 13 | 0 | 588 | 3,766 |
| 170 | idle2 | 3 | 3 | 3 | 4 | 0 | 0 | - | - |
| 180 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 199 sent, 199 ok, 0 errors

events:

    {"t": "2026-10-14T22:29:23.966-04:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-10-14T22:29:43.969-04:00", "rel_s": 20.0, "event": "load_start", "phase": "high"}
    {"t": "2026-10-14T22:29:48.589-04:00", "rel_s": 24.62, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "5"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:29:48.589-04:00", "rel_s": 24.62, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-4tf8t", "created": "2026-10-15T02:29:48Z"}
    {"t": "2026-10-14T22:29:48.589-04:00", "rel_s": 24.62, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-bblmf", "created": "2026-10-15T02:29:48Z"}
    {"t": "2026-10-14T22:29:51.605-04:00", "rel_s": 27.64, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-4tf8t"}
    {"t": "2026-10-14T22:29:51.606-04:00", "rel_s": 27.64, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-bblmf"}
    {"t": "2026-10-14T22:29:51.607-04:00", "rel_s": 27.64, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-bblmf"}
    {"t": "2026-10-14T22:29:55.623-04:00", "rel_s": 31.66, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-4tf8t"}
    {"t": "2026-10-14T22:31:04.584-04:00", "rel_s": 100.62, "event": "hpa_desired_change", "phase": "high", "old": 3, "new": 4, "hpa_metric": [{"external": {"current": {"averageValue": "2334m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:31:04.590-04:00", "rel_s": 100.63, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dw5g4", "created": "2026-10-15T02:31:03Z"}
    {"t": "2026-10-14T22:32:03.620-04:00", "rel_s": 159.66, "event": "pod_gone", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dw5g4"}
    {"t": "2026-10-14T22:32:04.620-04:00", "rel_s": 160.66, "event": "hpa_desired_change", "phase": "high", "old": 4, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "1250m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:32:16.294-04:00", "rel_s": 172.33, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-10-14T22:33:04.152-04:00", "rel_s": 220.19, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:33:04.153-04:00", "rel_s": 220.19, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-bblmf"}
    {"t": "2026-10-14T22:33:34.177-04:00", "rel_s": 250.21, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:33:34.179-04:00", "rel_s": 250.21, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-4tf8t"}
    {"t": "2026-10-14T22:33:54.393-04:00", "rel_s": 270.43, "event": "run_end", "phase": "idle2", "settled": true}
