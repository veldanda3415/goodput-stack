# loadgen sim-pool (SIMULATED backend)

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool sim --concurrency 8 --max-tokens 96 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util-sim/runs --prom http://10.43.105.58:9090`  started 2026-11-03T09:53:46.661-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 8 | 36 | 0 | 1,838 | 2,638 |
| 30 | high | 3 | 3 | 3 | 8 | 49 | 0 | 258 | 3,526 |
| 40 | high | 4 | 4 | 4 | 8 | 76 | 0 | 175 | 826 |
| 50 | high | 4 | 4 | 4 | 8 | 77 | 0 | 83 | 990 |
| 60 | high | 4 | 4 | 4 | 8 | 96 | 0 | 87 | 485 |
| 70 | high | 4 | 4 | 4 | 8 | 87 | 0 | 88 | 660 |
| 80 | high | 4 | 4 | 4 | 8 | 82 | 0 | 79 | 741 |
| 90 | high | 4 | 4 | 4 | 8 | 93 | 0 | 87 | 632 |
| 100 | high | 4 | 4 | 4 | 8 | 93 | 0 | 79 | 817 |
| 110 | high | 4 | 4 | 4 | 8 | 76 | 0 | 80 | 777 |
| 120 | high | 4 | 4 | 4 | 8 | 87 | 0 | 85 | 611 |
| 130 | high | 4 | 4 | 4 | 8 | 81 | 0 | 78 | 831 |
| 140 | high | 4 | 4 | 4 | 8 | 86 | 0 | 78 | 665 |
| 150 | high | 4 | 4 | 4 | 8 | 89 | 0 | 82 | 700 |
| 160 | high | 4 | 4 | 4 | 8 | 76 | 0 | 83 | 715 |
| 170 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 180 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 300 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 1184 sent, 1184 ok, 0 errors

events:

    {"t": "2026-11-03T09:53:46.080-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "sim-pool", "deploy": "inf-vllm-sim", "concurrency": 8, "max_tokens": 96, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:54:06.101-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:54:16.868-05:00", "rel_s": 30.79, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "8"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:54:16.868-05:00", "rel_s": 30.79, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-2d4jp", "created": "2026-11-03T14:54:16Z"}
    {"t": "2026-11-03T09:54:16.870-05:00", "rel_s": 30.79, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-vk9w7", "created": "2026-11-03T14:54:16Z"}
    {"t": "2026-11-03T09:54:19.316-05:00", "rel_s": 33.24, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-2d4jp"}
    {"t": "2026-11-03T09:54:19.317-05:00", "rel_s": 33.24, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-2d4jp"}
    {"t": "2026-11-03T09:54:19.319-05:00", "rel_s": 33.24, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-vk9w7"}
    {"t": "2026-11-03T09:54:20.321-05:00", "rel_s": 34.24, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-vk9w7"}
    {"t": "2026-11-03T09:54:31.940-05:00", "rel_s": 45.86, "event": "hpa_desired_change", "phase": "high", "old": 3, "new": 4, "hpa_metric": [{"external": {"current": {"averageValue": "2667m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:54:31.942-05:00", "rel_s": 45.86, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-j87j4", "created": "2026-11-03T14:54:31Z"}
    {"t": "2026-11-03T09:54:33.966-05:00", "rel_s": 47.89, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-j87j4"}
    {"t": "2026-11-03T09:54:33.968-05:00", "rel_s": 47.89, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-j87j4"}
    {"t": "2026-11-03T09:56:36.769-05:00", "rel_s": 170.69, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:57:32.012-05:00", "rel_s": 225.93, "event": "hpa_desired_change", "phase": "idle2", "old": 4, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:57:32.017-05:00", "rel_s": 225.94, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-2d4jp"}
    {"t": "2026-11-03T09:58:02.083-05:00", "rel_s": 256.0, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:58:02.086-05:00", "rel_s": 256.01, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-vk9w7"}
    {"t": "2026-11-03T09:58:32.142-05:00", "rel_s": 286.06, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-vllm-sim"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:58:32.144-05:00", "rel_s": 286.07, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-j87j4"}
    {"t": "2026-11-03T09:58:53.907-05:00", "rel_s": 307.83, "event": "run_end", "phase": "idle2", "settled": true}
