# loadgen sim-pool (SIMULATED backend)

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool sim --concurrency 8 --max-tokens 96 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util-sim/runs --prom http://10.43.105.58:9090 --hpa inf-vllm-sim-cpu`  started 2026-11-03T10:13:19.486-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 8 | 33 | 0 | 1,879 | 3,728 |
| 30 | high | 1 | 1 | 1 | 8 | 22 | 0 | 2,471 | 3,483 |
| 40 | high | 1 | 1 | 1 | 8 | 24 | 0 | 2,324 | 3,753 |
| 50 | high | 1 | 1 | 1 | 8 | 26 | 0 | 2,563 | 3,458 |
| 60 | high | 1 | 1 | 1 | 8 | 20 | 0 | 2,826 | 3,661 |
| 70 | high | 2 | 2 | 2 | 8 | 45 | 0 | 723 | 2,602 |
| 80 | high | 2 | 2 | 2 | 8 | 56 | 0 | 729 | 1,547 |
| 90 | high | 2 | 2 | 2 | 8 | 47 | 0 | 877 | 1,708 |
| 100 | high | 2 | 2 | 2 | 8 | 63 | 0 | 634 | 1,362 |
| 110 | high | 3 | 3 | 3 | 8 | 59 | 0 | 525 | 1,309 |
| 120 | high | 3 | 3 | 3 | 8 | 70 | 0 | 257 | 958 |
| 130 | high | 3 | 3 | 3 | 8 | 75 | 0 | 219 | 1,102 |
| 140 | high | 4 | 4 | 4 | 8 | 79 | 0 | 115 | 911 |
| 150 | high | 4 | 4 | 4 | 8 | 76 | 0 | 84 | 726 |
| 160 | high | 4 | 4 | 4 | 8 | 90 | 0 | 80 | 467 |
| 170 | idle2 | 4 | 4 | 4 | 7 | 0 | 0 | - | - |
| 180 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 300 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 310 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 320 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 330 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 340 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 350 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 360 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 785 sent, 785 ok, 0 errors

events:

    {"t": "2026-11-03T10:13:19.002-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "sim-pool", "deploy": "inf-vllm-sim", "concurrency": 8, "max_tokens": 96, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T10:13:39.022-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T10:14:29.314-05:00", "rel_s": 70.31, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 62, "averageValue": "62m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:14:29.314-05:00", "rel_s": 70.31, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mxrdk", "created": "2026-11-03T15:14:28Z"}
    {"t": "2026-11-03T10:14:31.314-05:00", "rel_s": 72.31, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mxrdk"}
    {"t": "2026-11-03T10:14:31.316-05:00", "rel_s": 72.32, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mxrdk"}
    {"t": "2026-11-03T10:15:14.030-05:00", "rel_s": 115.03, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 67, "averageValue": "67m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:15:14.033-05:00", "rel_s": 115.03, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-nkh7k", "created": "2026-11-03T15:15:12Z"}
    {"t": "2026-11-03T10:15:15.317-05:00", "rel_s": 116.32, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-nkh7k"}
    {"t": "2026-11-03T10:15:15.319-05:00", "rel_s": 116.32, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-nkh7k"}
    {"t": "2026-11-03T10:15:44.034-05:00", "rel_s": 145.03, "event": "hpa_desired_change", "phase": "high", "old": 3, "new": 4, "hpa_metric": [{"resource": {"current": {"averageUtilization": 65, "averageValue": "65m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:15:44.035-05:00", "rel_s": 145.03, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-j2djc", "created": "2026-11-03T15:15:43Z"}
    {"t": "2026-11-03T10:15:46.318-05:00", "rel_s": 147.32, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-j2djc"}
    {"t": "2026-11-03T10:15:46.320-05:00", "rel_s": 147.32, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-j2djc"}
    {"t": "2026-11-03T10:16:10.285-05:00", "rel_s": 171.28, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T10:17:29.316-05:00", "rel_s": 250.32, "event": "hpa_desired_change", "phase": "idle2", "old": 4, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 20, "averageValue": "20m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:17:29.323-05:00", "rel_s": 250.32, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-j2djc"}
    {"t": "2026-11-03T10:17:59.314-05:00", "rel_s": 280.31, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 20, "averageValue": "20m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:17:59.317-05:00", "rel_s": 280.32, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-mxrdk"}
    {"t": "2026-11-03T10:18:59.317-05:00", "rel_s": 340.32, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 21, "averageValue": "21m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:18:59.320-05:00", "rel_s": 340.32, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-nkh7k"}
    {"t": "2026-11-03T10:19:19.467-05:00", "rel_s": 360.47, "event": "run_end", "phase": "idle2", "settled": true}
