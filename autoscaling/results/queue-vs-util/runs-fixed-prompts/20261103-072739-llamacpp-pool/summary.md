# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T07:27:40.363-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 16 | 0 | 3,964 | 4,054 |
| 30 | high | 1 | 1 | 1 | 6 | 11 | 0 | 4,023 | 4,170 |
| 40 | high | 1 | 1 | 1 | 6 | 10 | 0 | 4,101 | 4,130 |
| 50 | high | 1 | 1 | 1 | 6 | 11 | 0 | 3,961 | 4,116 |
| 60 | high | 2 | 2 | 2 | 6 | 12 | 0 | 4,262 | 5,577 |
| 70 | high | 2 | 2 | 2 | 6 | 12 | 0 | 2,616 | 5,276 |
| 80 | high | 2 | 2 | 2 | 6 | 13 | 0 | 2,034 | 2,790 |
| 90 | high | 2 | 2 | 2 | 6 | 12 | 0 | 2,929 | 4,776 |
| 100 | high | 3 | 2 | 3 | 6 | 15 | 0 | 944 | 3,173 |
| 110 | high | 3 | 3 | 3 | 6 | 12 | 0 | 2,269 | 4,750 |
| 120 | high | 3 | 3 | 3 | 6 | 16 | 0 | 1,723 | 4,233 |
| 130 | high | 3 | 3 | 3 | 6 | 12 | 0 | 4,343 | 5,014 |
| 140 | high | 3 | 3 | 3 | 6 | 10 | 0 | 3,658 | 5,808 |
| 150 | high | 3 | 3 | 3 | 6 | 13 | 0 | 3,255 | 4,568 |
| 160 | high | 3 | 3 | 3 | 6 | 14 | 0 | 1,753 | 4,328 |
| 170 | idle2 | 3 | 3 | 3 | 5 | 0 | 0 | - | - |
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

requests: 189 sent, 189 ok, 0 errors

events:

    {"t": "2026-11-03T07:27:39.816-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:27:59.836-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:28:41.093-05:00", "rel_s": 61.28, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4003m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:28:41.095-05:00", "rel_s": 61.28, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-r64xj", "created": "2026-11-03T12:28:40Z"}
    {"t": "2026-11-03T07:28:44.320-05:00", "rel_s": 64.51, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-r64xj"}
    {"t": "2026-11-03T07:28:44.322-05:00", "rel_s": 64.51, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-r64xj"}
    {"t": "2026-11-03T07:29:26.318-05:00", "rel_s": 106.5, "event": "hpa_desired_change", "phase": "high", "old": 2, "new": 3, "hpa_metric": [{"resource": {"current": {"averageUtilization": 97, "averageValue": "3892m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:29:27.321-05:00", "rel_s": 107.51, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dprs2", "created": "2026-11-03T12:29:26Z"}
    {"t": "2026-11-03T07:29:30.323-05:00", "rel_s": 110.51, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dprs2"}
    {"t": "2026-11-03T07:29:32.342-05:00", "rel_s": 112.53, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-dprs2"}
    {"t": "2026-11-03T07:30:34.058-05:00", "rel_s": 174.24, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:31:41.316-05:00", "rel_s": 241.5, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-dprs2"}
    {"t": "2026-11-03T07:31:41.802-05:00", "rel_s": 241.99, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:32:11.315-05:00", "rel_s": 271.5, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-r64xj"}
    {"t": "2026-11-03T07:32:11.808-05:00", "rel_s": 271.99, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:32:32.178-05:00", "rel_s": 292.36, "event": "run_end", "phase": "idle2", "settled": true}
