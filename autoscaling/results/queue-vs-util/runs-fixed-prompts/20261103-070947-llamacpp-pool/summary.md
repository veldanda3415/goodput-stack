# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T07:09:47.481-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 14 | 0 | 4,542 | 4,896 |
| 30 | high | 2 | 1 | 2 | 6 | 8 | 0 | 4,525 | 4,628 |
| 40 | high | 2 | 2 | 2 | 6 | 12 | 0 | 2,456 | 5,712 |
| 50 | high | 2 | 2 | 2 | 6 | 13 | 0 | 1,623 | 2,904 |
| 60 | high | 3 | 2 | 3 | 6 | 15 | 0 | 1,692 | 3,209 |
| 70 | high | 3 | 3 | 3 | 6 | 15 | 0 | 1,172 | 2,090 |
| 80 | high | 3 | 3 | 3 | 6 | 14 | 0 | 466 | 3,190 |
| 90 | high | 3 | 3 | 3 | 6 | 14 | 0 | 471 | 994 |
| 100 | high | 3 | 3 | 3 | 6 | 16 | 0 | 485 | 3,756 |
| 110 | high | 3 | 3 | 3 | 6 | 14 | 0 | 471 | 2,085 |
| 120 | high | 3 | 3 | 3 | 6 | 16 | 0 | 596 | 2,132 |
| 130 | high | 3 | 3 | 3 | 6 | 13 | 0 | 478 | 2,299 |
| 140 | high | 3 | 3 | 3 | 6 | 16 | 0 | 471 | 2,917 |
| 150 | high | 3 | 3 | 3 | 6 | 13 | 0 | 785 | 2,595 |
| 160 | high | 3 | 3 | 3 | 6 | 17 | 0 | 487 | 2,591 |
| 170 | idle2 | 3 | 3 | 3 | 6 | 0 | 0 | - | - |
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
| 300 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 210 sent, 210 ok, 0 errors

events:

    {"t": "2026-11-03T07:09:47.024-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:10:07.042-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:10:25.315-05:00", "rel_s": 38.29, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 65, "averageValue": "2609m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:10:25.882-05:00", "rel_s": 38.86, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-hrdm6", "created": "2026-11-03T12:10:25Z"}
    {"t": "2026-11-03T07:10:30.316-05:00", "rel_s": 43.29, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-hrdm6"}
    {"t": "2026-11-03T07:10:31.322-05:00", "rel_s": 44.3, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-hrdm6"}
    {"t": "2026-11-03T07:10:55.282-05:00", "rel_s": 68.26, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 99, "averageValue": "3961m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:10:55.286-05:00", "rel_s": 68.26, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-llhvh", "created": "2026-11-03T12:10:54Z"}
    {"t": "2026-11-03T07:11:00.345-05:00", "rel_s": 73.32, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-llhvh"}
    {"t": "2026-11-03T07:11:00.347-05:00", "rel_s": 73.32, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-llhvh"}
    {"t": "2026-11-03T07:12:40.628-05:00", "rel_s": 173.61, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:13:55.317-05:00", "rel_s": 248.29, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:13:55.319-05:00", "rel_s": 248.3, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-llhvh"}
    {"t": "2026-11-03T07:14:25.315-05:00", "rel_s": 278.29, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-hrdm6"}
    {"t": "2026-11-03T07:14:26.316-05:00", "rel_s": 279.29, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "11m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:14:46.750-05:00", "rel_s": 299.73, "event": "run_end", "phase": "idle2", "settled": true}
