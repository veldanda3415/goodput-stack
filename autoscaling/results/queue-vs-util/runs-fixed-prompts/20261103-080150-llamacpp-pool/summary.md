# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T08:01:50.885-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 12 | 0 | 223 | 239 |
| 30 | high | 1 | 1 | 1 | 2 | 11 | 0 | 225 | 236 |
| 40 | high | 1 | 1 | 1 | 2 | 11 | 0 | 227 | 237 |
| 50 | high | 1 | 1 | 1 | 2 | 10 | 0 | 242 | 269 |
| 60 | high | 2 | 1 | 2 | 2 | 11 | 0 | 220 | 279 |
| 70 | high | 2 | 2 | 2 | 2 | 10 | 0 | 239 | 249 |
| 80 | high | 2 | 2 | 2 | 2 | 11 | 0 | 237 | 264 |
| 90 | high | 2 | 2 | 2 | 2 | 10 | 0 | 234 | 261 |
| 100 | high | 2 | 2 | 2 | 2 | 12 | 0 | 231 | 246 |
| 110 | high | 2 | 2 | 2 | 2 | 10 | 0 | 232 | 263 |
| 120 | high | 2 | 2 | 2 | 2 | 11 | 0 | 246 | 258 |
| 130 | high | 2 | 2 | 2 | 2 | 11 | 0 | 231 | 259 |
| 140 | high | 2 | 2 | 2 | 2 | 11 | 0 | 247 | 275 |
| 150 | high | 2 | 2 | 2 | 2 | 10 | 0 | 238 | 262 |
| 160 | high | 2 | 2 | 2 | 2 | 12 | 0 | 236 | 259 |
| 170 | idle2 | 2 | 2 | 2 | 1 | 0 | 0 | - | - |
| 180 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 163 sent, 163 ok, 0 errors

events:

    {"t": "2026-11-03T08:01:50.338-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:02:10.341-05:00", "rel_s": 20.0, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:02:59.201-05:00", "rel_s": 68.86, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4010m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:02:59.202-05:00", "rel_s": 68.86, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-p2s5v", "created": "2026-11-03T13:02:58Z"}
    {"t": "2026-11-03T08:03:02.255-05:00", "rel_s": 71.92, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-p2s5v"}
    {"t": "2026-11-03T08:04:41.510-05:00", "rel_s": 171.17, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T08:05:44.316-05:00", "rel_s": 233.98, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T08:05:44.317-05:00", "rel_s": 233.98, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-p2s5v"}
    {"t": "2026-11-03T08:06:04.588-05:00", "rel_s": 254.25, "event": "run_end", "phase": "idle2", "settled": true}
