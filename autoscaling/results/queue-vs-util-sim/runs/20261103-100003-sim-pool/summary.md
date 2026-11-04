# loadgen sim-pool (SIMULATED backend)

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool sim --concurrency 8 --max-tokens 96 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util-sim/runs --prom http://10.43.105.58:9090 --hpa inf-vllm-sim-cpu`  started 2026-11-03T10:00:03.786-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 8 | 36 | 0 | 1,982 | 2,709 |
| 30 | high | 1 | 1 | 1 | 8 | 24 | 0 | 2,348 | 2,950 |
| 40 | high | 1 | 1 | 1 | 8 | 21 | 0 | 3,129 | 3,707 |
| 50 | high | 2 | 2 | 2 | 8 | 38 | 0 | 890 | 3,529 |
| 60 | high | 2 | 2 | 2 | 8 | 56 | 0 | 734 | 1,589 |
| 70 | high | 2 | 2 | 2 | 8 | 56 | 0 | 704 | 1,643 |
| 80 | high | 3 | 3 | 3 | 8 | 68 | 0 | 384 | 1,279 |
| 90 | high | 3 | 3 | 3 | 8 | 72 | 0 | 229 | 943 |
| 100 | high | 3 | 3 | 3 | 8 | 72 | 0 | 270 | 976 |
| 110 | high | 3 | 3 | 3 | 8 | 72 | 0 | 256 | 1,030 |
| 120 | high | 4 | 3 | 4 | 8 | 67 | 0 | 173 | 1,180 |
| 130 | high | 4 | 4 | 4 | 8 | 87 | 0 | 88 | 698 |
| 140 | high | 4 | 4 | 4 | 8 | 79 | 0 | 85 | 583 |
| 150 | high | 4 | 4 | 4 | 8 | 91 | 0 | 81 | 842 |
| 160 | high | 4 | 4 | 4 | 8 | 85 | 0 | 84 | 725 |
| 170 | idle2 | 4 | 4 | 4 | 7 | 0 | 0 | - | - |
| 180 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 4 | 4 | 4 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 300 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 310 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 320 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 330 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 340 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 350 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 924 sent, 924 ok, 0 errors

events:

    {"t": "2026-11-03T10:00:03.178-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "sim-pool", "deploy": "inf-vllm-sim", "concurrency": 8, "max_tokens": 96, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T10:00:23.197-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T10:00:57.270-05:00", "rel_s": 54.09, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 68, "averageValue": "68m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:00:57.273-05:00", "rel_s": 54.1, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-qkm7r", "created": "2026-11-03T15:00:55Z"}
    {"t": "2026-11-03T10:00:58.317-05:00", "rel_s": 55.14, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-qkm7r"}
    {"t": "2026-11-03T10:00:59.320-05:00", "rel_s": 56.14, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-qkm7r"}
    {"t": "2026-11-03T10:01:26.963-05:00", "rel_s": 83.79, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 67, "averageValue": "67m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:01:26.968-05:00", "rel_s": 83.79, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-vhfn8", "created": "2026-11-03T15:01:26Z"}
    {"t": "2026-11-03T10:01:28.320-05:00", "rel_s": 85.14, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-vhfn8"}
    {"t": "2026-11-03T10:01:28.323-05:00", "rel_s": 85.15, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-vhfn8"}
    {"t": "2026-11-03T10:02:12.317-05:00", "rel_s": 129.14, "event": "hpa_desired_change", "phase": "high", "old": 3, "new": 4, "hpa_metric": [{"resource": {"current": {"averageUtilization": 62, "averageValue": "62m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:02:12.318-05:00", "rel_s": 129.14, "event": "pod_created", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mw5rm", "created": "2026-11-03T15:02:10Z"}
    {"t": "2026-11-03T10:02:13.318-05:00", "rel_s": 130.14, "event": "pod_ready", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mw5rm"}
    {"t": "2026-11-03T10:02:13.320-05:00", "rel_s": 130.14, "event": "pod_first_served", "phase": "high", "pod": "inf-vllm-sim-7565c9d79d-mw5rm"}
    {"t": "2026-11-03T10:02:54.560-05:00", "rel_s": 171.38, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T10:04:11.851-05:00", "rel_s": 248.68, "event": "hpa_desired_change", "phase": "idle2", "old": 4, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 22, "averageValue": "22m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:04:11.856-05:00", "rel_s": 248.68, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-mw5rm"}
    {"t": "2026-11-03T10:04:41.936-05:00", "rel_s": 278.76, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 22, "averageValue": "22m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:04:41.939-05:00", "rel_s": 278.76, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-vhfn8"}
    {"t": "2026-11-03T10:05:41.871-05:00", "rel_s": 338.7, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 21, "averageValue": "21m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T10:05:41.873-05:00", "rel_s": 338.7, "event": "pod_gone", "phase": "idle2", "pod": "inf-vllm-sim-7565c9d79d-qkm7r"}
    {"t": "2026-11-03T10:06:02.744-05:00", "rel_s": 359.57, "event": "run_end", "phase": "idle2", "settled": true}
