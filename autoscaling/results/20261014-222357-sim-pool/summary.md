# loadgen sim-pool (SIMULATED backend)

`autoscaling/loadgen.py --pool sim --concurrency 8 --max-tokens 96 --idle 20 --high 150 --tail 300`  started 2026-10-14T22:23:58.101-04:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 8 | 28 | 0 | 2,710 | 3,750 |
| 30 | high | 3 | 3 | 3 | 8 | 31 | 0 | 1,728 | 3,307 |
| 40 | high | 3 | 3 | 3 | 8 | 74 | 0 | 272 | 914 |
| 50 | high | 4 | 4 | 4 | 8 | 84 | 0 | 110 | 582 |
| 60 | high | 4 | 4 | 4 | 8 | 81 | 0 | 84 | 774 |
| 70 | high | 4 | 4 | 4 | 8 | 81 | 0 | 81 | 790 |
| 80 | high | 4 | 4 | 4 | 8 | 97 | 0 | 91 | 557 |
| 90 | high | 4 | 4 | 4 | 8 | 85 | 0 | 91 | 598 |
| 100 | high | 4 | 4 | 4 | 8 | 76 | 0 | 85 | 845 |
| 110 | high | 4 | 4 | 4 | 8 | 79 | 0 | 86 | 601 |
| 120 | high | 4 | 4 | 4 | 8 | 90 | 0 | 89 | 679 |
| 130 | high | 4 | 4 | 4 | 8 | 86 | 0 | 93 | 817 |
| 140 | high | 4 | 4 | 4 | 8 | 83 | 0 | 85 | 641 |
| 150 | high | 4 | 4 | 4 | 8 | 84 | 0 | 85 | 727 |
| 160 | high | 4 | 4 | 4 | 8 | 85 | 0 | 83 | 742 |
| 170 | idle2 | 4 | 4 | 4 | 2 | 0 | 0 | - | - |
| 180 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 300 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 310 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 1144 sent, 1144 ok, 0 errors

events:

    {"t": "2026-10-14T22:23:57.567-04:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "sim-pool", "deploy": "inf-vllm-sim", "concurrency": 8, "max_tokens": 96, "idle": 20.0, "high": 150.0}
    {"t": "2026-10-14T22:24:17.572-04:00", "rel_s": 20.01, "event": "load_start", "phase": "high"}
    {"t": "2026-10-14T22:24:33.244-04:00", "rel_s": 35.68, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "8"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:24:33.244-04:00", "rel_s": 35.68, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-65t9s", "created": "2026-10-15T02:24:32Z"}
    {"t": "2026-10-14T22:24:33.244-04:00", "rel_s": 35.68, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-7bh9b", "created": "2026-10-15T02:24:32Z"}
    {"t": "2026-10-14T22:24:35.553-04:00", "rel_s": 37.99, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-65t9s"}
    {"t": "2026-10-14T22:24:35.555-04:00", "rel_s": 37.99, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-7bh9b"}
    {"t": "2026-10-14T22:24:35.556-04:00", "rel_s": 37.99, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-7bh9b"}
    {"t": "2026-10-14T22:24:36.156-04:00", "rel_s": 38.59, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-65t9s"}
    {"t": "2026-10-14T22:24:48.232-04:00", "rel_s": 50.67, "event": "hpa_desired_change", "phase": "high", "old": 3, "new": 4, "hpa_metric": [{"external": {"current": {"averageValue": "2667m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:24:49.571-04:00", "rel_s": 52.01, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-9phdf", "created": "2026-10-15T02:24:48Z"}
    {"t": "2026-10-14T22:24:50.617-04:00", "rel_s": 53.05, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-9phdf"}
    {"t": "2026-10-14T22:24:50.619-04:00", "rel_s": 53.05, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-9phdf"}
    {"t": "2026-10-14T22:26:48.831-04:00", "rel_s": 171.27, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-10-14T22:27:48.613-04:00", "rel_s": 231.05, "event": "hpa_desired_change", "phase": "idle2", "old": 4, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:27:48.620-04:00", "rel_s": 231.05, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-9phdf"}
    {"t": "2026-10-14T22:28:18.610-04:00", "rel_s": 261.04, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:28:18.613-04:00", "rel_s": 261.05, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-7bh9b"}
    {"t": "2026-10-14T22:28:48.609-04:00", "rel_s": 291.04, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-10-14T22:28:48.611-04:00", "rel_s": 291.05, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-65t9s"}
    {"t": "2026-10-14T22:29:09.962-04:00", "rel_s": 312.4, "event": "run_end", "phase": "idle2", "settled": true}
