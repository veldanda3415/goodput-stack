# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T09:13:34.826-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 10 | 0 | 340 | 583 |
| 30 | high | 1 | 1 | 1 | 2 | 10 | 0 | 420 | 552 |
| 40 | high | 2 | 1 | 2 | 2 | 10 | 0 | 432 | 627 |
| 50 | high | 2 | 2 | 2 | 2 | 8 | 0 | 401 | 613 |
| 60 | high | 2 | 2 | 2 | 2 | 10 | 0 | 427 | 622 |
| 70 | high | 2 | 2 | 2 | 2 | 8 | 0 | 417 | 623 |
| 80 | high | 2 | 2 | 2 | 2 | 11 | 0 | 413 | 581 |
| 90 | high | 3 | 3 | 3 | 2 | 8 | 0 | 436 | 469 |
| 100 | high | 3 | 3 | 3 | 2 | 9 | 0 | 450 | 471 |
| 110 | high | 3 | 3 | 3 | 2 | 10 | 0 | 410 | 566 |
| 120 | high | 3 | 3 | 3 | 2 | 9 | 0 | 425 | 580 |
| 130 | high | 3 | 3 | 3 | 2 | 9 | 0 | 432 | 574 |
| 140 | high | 3 | 3 | 3 | 2 | 10 | 0 | 430 | 650 |
| 150 | high | 3 | 3 | 3 | 2 | 9 | 0 | 392 | 465 |
| 160 | high | 3 | 3 | 3 | 2 | 10 | 0 | 432 | 520 |
| 170 | idle2 | 3 | 3 | 3 | 2 | 0 | 0 | - | - |
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

requests: 141 sent, 141 ok, 0 errors

events:

    {"t": "2026-11-03T09:13:34.244-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:13:54.262-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:14:20.236-05:00", "rel_s": 45.99, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 85, "averageValue": "3422m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:14:20.236-05:00", "rel_s": 45.99, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fd96n", "created": "2026-11-03T14:14:19Z"}
    {"t": "2026-11-03T09:14:24.322-05:00", "rel_s": 50.08, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fd96n"}
    {"t": "2026-11-03T09:14:24.323-05:00", "rel_s": 50.08, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fd96n"}
    {"t": "2026-11-03T09:15:05.283-05:00", "rel_s": 91.04, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 82, "averageValue": "3305m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:15:05.286-05:00", "rel_s": 91.04, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-mf2lm", "created": "2026-11-03T14:15:04Z"}
    {"t": "2026-11-03T09:15:07.332-05:00", "rel_s": 93.09, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-mf2lm"}
    {"t": "2026-11-03T09:15:09.241-05:00", "rel_s": 95.0, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-mf2lm"}
    {"t": "2026-11-03T09:16:26.106-05:00", "rel_s": 171.86, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:17:35.315-05:00", "rel_s": 241.07, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:17:35.317-05:00", "rel_s": 241.07, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-mf2lm"}
    {"t": "2026-11-03T09:18:05.315-05:00", "rel_s": 271.07, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:18:05.316-05:00", "rel_s": 271.07, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-fd96n"}
    {"t": "2026-11-03T09:18:26.228-05:00", "rel_s": 291.98, "event": "run_end", "phase": "idle2", "settled": true}
