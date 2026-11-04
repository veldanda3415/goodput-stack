# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T08:50:17.066-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 14 | 0 | 4,395 | 4,507 |
| 30 | high | 2 | 1 | 2 | 6 | 10 | 0 | 4,797 | 5,694 |
| 40 | high | 2 | 2 | 2 | 6 | 10 | 0 | 1,338 | 4,906 |
| 50 | high | 3 | 3 | 3 | 6 | 12 | 0 | 1,312 | 3,624 |
| 60 | high | 3 | 3 | 3 | 6 | 16 | 0 | 595 | 2,964 |
| 70 | high | 3 | 3 | 3 | 6 | 14 | 0 | 617 | 2,654 |
| 80 | high | 3 | 3 | 3 | 6 | 15 | 0 | 591 | 2,358 |
| 90 | high | 3 | 3 | 3 | 6 | 14 | 0 | 619 | 2,205 |
| 100 | high | 3 | 3 | 3 | 6 | 14 | 0 | 599 | 2,280 |
| 110 | high | 3 | 3 | 3 | 6 | 15 | 0 | 883 | 3,729 |
| 120 | high | 3 | 3 | 3 | 6 | 10 | 0 | 618 | 2,615 |
| 130 | high | 3 | 3 | 3 | 6 | 18 | 0 | 588 | 3,972 |
| 140 | high | 3 | 3 | 3 | 6 | 14 | 0 | 610 | 2,143 |
| 150 | high | 3 | 3 | 3 | 6 | 13 | 0 | 614 | 3,360 |
| 160 | high | 3 | 3 | 3 | 6 | 14 | 0 | 661 | 2,782 |
| 170 | idle2 | 3 | 3 | 3 | 3 | 0 | 0 | - | - |
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

requests: 203 sent, 203 ok, 0 errors

events:

    {"t": "2026-11-03T08:50:16.514-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:50:36.534-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:50:55.222-05:00", "rel_s": 38.71, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "3833m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T08:50:56.223-05:00", "rel_s": 39.71, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7knkm", "created": "2026-11-03T13:50:55Z"}
    {"t": "2026-11-03T08:50:59.271-05:00", "rel_s": 42.76, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7knkm"}
    {"t": "2026-11-03T08:50:59.273-05:00", "rel_s": 42.76, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7knkm"}
    {"t": "2026-11-03T08:51:10.415-05:00", "rel_s": 53.9, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "3417m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T08:51:10.417-05:00", "rel_s": 53.9, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7x9q6", "created": "2026-11-03T13:51:09Z"}
    {"t": "2026-11-03T08:51:13.325-05:00", "rel_s": 56.81, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7x9q6"}
    {"t": "2026-11-03T08:51:14.342-05:00", "rel_s": 57.83, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-7x9q6"}
    {"t": "2026-11-03T08:53:09.468-05:00", "rel_s": 172.96, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:54:11.023-05:00", "rel_s": 234.51, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T08:54:11.025-05:00", "rel_s": 234.51, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-7x9q6"}
    {"t": "2026-11-03T08:54:41.005-05:00", "rel_s": 264.49, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T08:54:41.006-05:00", "rel_s": 264.49, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-7knkm"}
    {"t": "2026-11-03T08:55:01.576-05:00", "rel_s": 285.06, "event": "run_end", "phase": "idle2", "settled": true}
