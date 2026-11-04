# loadgen sim-pool (SIMULATED backend)

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool sim --concurrency 8 --max-tokens 96 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util-sim/runs --prom http://10.43.105.58:9090`  started 2026-11-03T10:07:14.009-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 8 | 31 | 0 | 2,156 | 2,629 |
| 30 | high | 3 | 3 | 3 | 8 | 27 | 0 | 2,413 | 3,684 |
| 40 | high | 3 | 3 | 3 | 8 | 68 | 0 | 244 | 1,008 |
| 50 | high | 4 | 4 | 4 | 8 | 79 | 0 | 95 | 847 |
| 60 | high | 4 | 4 | 4 | 8 | 85 | 0 | 86 | 675 |
| 70 | high | 4 | 4 | 4 | 8 | 84 | 0 | 92 | 751 |
| 80 | high | 4 | 4 | 4 | 8 | 75 | 0 | 84 | 690 |
| 90 | high | 4 | 4 | 4 | 8 | 92 | 0 | 82 | 595 |
| 100 | high | 4 | 4 | 4 | 8 | 85 | 0 | 79 | 686 |
| 110 | high | 4 | 4 | 4 | 8 | 91 | 0 | 81 | 663 |
| 120 | high | 4 | 4 | 4 | 8 | 75 | 0 | 86 | 878 |
| 130 | high | 4 | 4 | 4 | 8 | 88 | 0 | 85 | 490 |
| 140 | high | 4 | 4 | 4 | 8 | 77 | 0 | 89 | 671 |
| 150 | high | 4 | 4 | 4 | 8 | 92 | 0 | 87 | 655 |
| 160 | high | 4 | 4 | 4 | 8 | 82 | 0 | 84 | 747 |
| 170 | idle2 | 4 | 4 | 4 | 2 | 0 | 0 | - | - |
| 180 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 1131 sent, 1131 ok, 0 errors

events:

    {"t": "2026-11-03T10:07:13.408-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "sim-pool", "deploy": "inf-vllm-sim", "concurrency": 8, "max_tokens": 96, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T10:07:33.426-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T10:07:50.145-05:00", "rel_s": 36.74, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "8"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T10:07:51.317-05:00", "rel_s": 37.91, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-cjwjv", "created": "2026-11-03T15:07:50Z"}
    {"t": "2026-11-03T10:07:51.318-05:00", "rel_s": 37.91, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mfxfg", "created": "2026-11-03T15:07:50Z"}
    {"t": "2026-11-03T10:07:52.898-05:00", "rel_s": 39.49, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-cjwjv"}
    {"t": "2026-11-03T10:07:52.900-05:00", "rel_s": 39.49, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-cjwjv"}
    {"t": "2026-11-03T10:07:52.901-05:00", "rel_s": 39.49, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mfxfg"}
    {"t": "2026-11-03T10:07:52.902-05:00", "rel_s": 39.5, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mfxfg"}
    {"t": "2026-11-03T10:08:05.135-05:00", "rel_s": 51.73, "event": "hpa_desired_change", "phase": "high", "old": 3, "new": 4, "hpa_metric": [{"external": {"current": {"averageValue": "2667m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T10:08:05.140-05:00", "rel_s": 51.73, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-p69f9", "created": "2026-11-03T15:08:04Z"}
    {"t": "2026-11-03T10:08:06.905-05:00", "rel_s": 53.5, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-p69f9"}
    {"t": "2026-11-03T10:08:06.907-05:00", "rel_s": 53.5, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-p69f9"}
    {"t": "2026-11-03T10:10:04.894-05:00", "rel_s": 171.49, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T10:10:50.329-05:00", "rel_s": 216.92, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-mfxfg"}
    {"t": "2026-11-03T10:10:50.903-05:00", "rel_s": 217.5, "event": "hpa_desired_change", "phase": "idle2", "old": 4, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T10:11:20.318-05:00", "rel_s": 246.91, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-cjwjv"}
    {"t": "2026-11-03T10:11:20.923-05:00", "rel_s": 247.52, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T10:11:50.315-05:00", "rel_s": 276.91, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-p69f9"}
    {"t": "2026-11-03T10:11:50.911-05:00", "rel_s": 277.5, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T10:12:11.017-05:00", "rel_s": 297.61, "event": "run_end", "phase": "idle2", "settled": true}
