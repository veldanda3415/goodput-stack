# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T08:33:32.373-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 15 | 0 | 4,420 | 4,500 |
| 30 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,544 | 4,586 |
| 40 | high | 1 | 1 | 1 | 6 | 9 | 0 | 4,505 | 4,582 |
| 50 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,356 | 4,461 |
| 60 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,434 | 4,532 |
| 70 | high | 2 | 2 | 2 | 6 | 8 | 0 | 4,747 | 6,090 |
| 80 | high | 2 | 2 | 2 | 6 | 14 | 0 | 1,980 | 3,391 |
| 90 | high | 2 | 2 | 2 | 6 | 12 | 0 | 1,964 | 3,644 |
| 100 | high | 2 | 2 | 2 | 6 | 14 | 0 | 2,093 | 3,508 |
| 110 | high | 3 | 2 | 3 | 6 | 12 | 0 | 2,029 | 2,821 |
| 120 | high | 3 | 3 | 3 | 6 | 13 | 0 | 899 | 2,998 |
| 130 | high | 3 | 3 | 3 | 6 | 15 | 0 | 647 | 2,716 |
| 140 | high | 3 | 3 | 3 | 6 | 14 | 0 | 847 | 2,942 |
| 150 | high | 3 | 3 | 3 | 6 | 15 | 0 | 602 | 2,240 |
| 160 | high | 3 | 3 | 3 | 6 | 15 | 0 | 655 | 3,312 |
| 170 | idle2 | 3 | 3 | 3 | 6 | 0 | 0 | - | - |
| 180 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 290 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 300 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 186 sent, 186 ok, 0 errors

events:

    {"t": "2026-11-03T08:33:31.832-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:33:51.853-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:34:44.919-05:00", "rel_s": 73.09, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-gql8d", "created": "2026-11-03T13:34:44Z"}
    {"t": "2026-11-03T08:34:45.937-05:00", "rel_s": 74.11, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4004m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:34:48.315-05:00", "rel_s": 76.48, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-gql8d"}
    {"t": "2026-11-03T08:34:48.928-05:00", "rel_s": 77.1, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-gql8d"}
    {"t": "2026-11-03T08:35:31.320-05:00", "rel_s": 119.49, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 98, "averageValue": "3946m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:35:31.323-05:00", "rel_s": 119.49, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-pnq8v", "created": "2026-11-03T13:35:30Z"}
    {"t": "2026-11-03T08:35:34.350-05:00", "rel_s": 122.52, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-pnq8v"}
    {"t": "2026-11-03T08:35:34.351-05:00", "rel_s": 122.52, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-pnq8v"}
    {"t": "2026-11-03T08:36:25.079-05:00", "rel_s": 173.25, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:37:46.318-05:00", "rel_s": 254.49, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:37:46.320-05:00", "rel_s": 254.49, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-pnq8v"}
    {"t": "2026-11-03T08:38:16.313-05:00", "rel_s": 284.48, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:38:16.315-05:00", "rel_s": 284.48, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-gql8d"}
    {"t": "2026-11-03T08:38:37.212-05:00", "rel_s": 305.38, "event": "run_end", "phase": "idle2", "settled": true}
