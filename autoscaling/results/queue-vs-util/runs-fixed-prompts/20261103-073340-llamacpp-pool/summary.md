# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T07:33:40.597-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 16 | 0 | 3,999 | 4,052 |
| 30 | high | 1 | 1 | 1 | 6 | 11 | 0 | 4,015 | 4,084 |
| 40 | high | 1 | 1 | 1 | 6 | 11 | 0 | 3,262 | 4,204 |
| 50 | high | 1 | 1 | 1 | 6 | 11 | 0 | 3,995 | 4,088 |
| 60 | high | 2 | 2 | 2 | 6 | 11 | 0 | 4,124 | 5,223 |
| 70 | high | 2 | 2 | 2 | 6 | 12 | 0 | 3,457 | 5,237 |
| 80 | high | 2 | 2 | 2 | 6 | 13 | 0 | 2,611 | 5,159 |
| 90 | high | 2 | 2 | 2 | 6 | 13 | 0 | 3,214 | 4,667 |
| 100 | high | 2 | 2 | 2 | 6 | 14 | 0 | 2,731 | 5,655 |
| 110 | high | 2 | 2 | 2 | 6 | 12 | 0 | 376 | 4,309 |
| 120 | high | 3 | 3 | 3 | 6 | 15 | 0 | 2,014 | 3,630 |
| 130 | high | 3 | 3 | 3 | 6 | 10 | 0 | 2,496 | 6,102 |
| 140 | high | 3 | 3 | 3 | 6 | 14 | 0 | 3,040 | 5,236 |
| 150 | high | 3 | 3 | 3 | 6 | 11 | 0 | 544 | 5,216 |
| 160 | high | 3 | 3 | 3 | 6 | 14 | 0 | 1,270 | 3,933 |
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

requests: 188 sent, 188 ok, 0 errors

events:

    {"t": "2026-11-03T07:33:40.039-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:34:00.059-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:34:41.982-05:00", "rel_s": 61.94, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4009m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:34:41.985-05:00", "rel_s": 61.95, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-ldmdx", "created": "2026-11-03T12:34:41Z"}
    {"t": "2026-11-03T07:34:45.316-05:00", "rel_s": 65.28, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-ldmdx"}
    {"t": "2026-11-03T07:34:47.320-05:00", "rel_s": 67.28, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-ldmdx"}
    {"t": "2026-11-03T07:35:41.321-05:00", "rel_s": 121.28, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-45b2v", "created": "2026-11-03T12:35:41Z"}
    {"t": "2026-11-03T07:35:42.206-05:00", "rel_s": 122.17, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 96, "averageValue": "3874m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:35:45.318-05:00", "rel_s": 125.28, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-45b2v"}
    {"t": "2026-11-03T07:35:47.324-05:00", "rel_s": 127.29, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-45b2v"}
    {"t": "2026-11-03T07:36:32.765-05:00", "rel_s": 172.73, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:37:41.937-05:00", "rel_s": 241.9, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:37:41.939-05:00", "rel_s": 241.9, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-45b2v"}
    {"t": "2026-11-03T07:38:12.314-05:00", "rel_s": 272.28, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:38:12.315-05:00", "rel_s": 272.28, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-ldmdx"}
    {"t": "2026-11-03T07:38:32.880-05:00", "rel_s": 292.84, "event": "run_end", "phase": "idle2", "settled": true}
