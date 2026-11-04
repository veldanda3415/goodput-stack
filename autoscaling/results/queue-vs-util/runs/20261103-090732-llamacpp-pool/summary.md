# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T09:07:32.683-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 15 | 0 | 3,462 | 4,489 |
| 30 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,467 | 4,515 |
| 40 | high | 2 | 1 | 2 | 6 | 9 | 0 | 4,663 | 5,218 |
| 50 | high | 2 | 2 | 2 | 6 | 11 | 0 | 1,376 | 4,511 |
| 60 | high | 2 | 2 | 2 | 6 | 14 | 0 | 1,448 | 3,338 |
| 70 | high | 3 | 2 | 3 | 6 | 12 | 0 | 2,419 | 3,557 |
| 80 | high | 3 | 3 | 3 | 6 | 13 | 0 | 619 | 2,941 |
| 90 | high | 3 | 3 | 3 | 6 | 13 | 0 | 600 | 4,482 |
| 100 | high | 3 | 3 | 3 | 6 | 13 | 0 | 959 | 3,325 |
| 110 | high | 3 | 3 | 3 | 6 | 15 | 0 | 637 | 3,480 |
| 120 | high | 3 | 3 | 3 | 6 | 11 | 0 | 601 | 3,867 |
| 130 | high | 3 | 3 | 3 | 6 | 16 | 0 | 635 | 1,549 |
| 140 | high | 3 | 3 | 3 | 6 | 13 | 0 | 1,033 | 3,203 |
| 150 | high | 3 | 3 | 3 | 6 | 15 | 0 | 610 | 4,058 |
| 160 | high | 3 | 3 | 3 | 6 | 13 | 0 | 628 | 3,668 |
| 170 | idle2 | 3 | 3 | 3 | 4 | 0 | 0 | - | - |
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

requests: 193 sent, 193 ok, 0 errors

events:

    {"t": "2026-11-03T09:07:32.127-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T09:07:52.135-05:00", "rel_s": 20.01, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T09:08:20.060-05:00", "rel_s": 47.93, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4006m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:08:20.076-05:00", "rel_s": 47.95, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fg588", "created": "2026-11-03T14:08:19Z"}
    {"t": "2026-11-03T09:08:23.317-05:00", "rel_s": 51.19, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fg588"}
    {"t": "2026-11-03T09:08:24.244-05:00", "rel_s": 52.12, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-fg588"}
    {"t": "2026-11-03T09:08:49.077-05:00", "rel_s": 76.95, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 98, "averageValue": "3953m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:08:49.080-05:00", "rel_s": 76.95, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-r4bnz", "created": "2026-11-03T14:08:48Z"}
    {"t": "2026-11-03T09:08:52.317-05:00", "rel_s": 80.19, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-r4bnz"}
    {"t": "2026-11-03T09:08:52.319-05:00", "rel_s": 80.19, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-r4bnz"}
    {"t": "2026-11-03T09:10:25.234-05:00", "rel_s": 173.11, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:11:34.315-05:00", "rel_s": 242.19, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:11:34.317-05:00", "rel_s": 242.19, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-fg588"}
    {"t": "2026-11-03T09:12:04.315-05:00", "rel_s": 272.19, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T09:12:04.316-05:00", "rel_s": 272.19, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-r4bnz"}
    {"t": "2026-11-03T09:12:25.359-05:00", "rel_s": 293.23, "event": "run_end", "phase": "idle2", "settled": true}
