# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T07:44:04.957-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 12 | 0 | 222 | 232 |
| 30 | high | 1 | 1 | 1 | 2 | 11 | 0 | 224 | 242 |
| 40 | high | 1 | 1 | 1 | 2 | 10 | 0 | 227 | 246 |
| 50 | high | 2 | 2 | 2 | 2 | 11 | 0 | 246 | 278 |
| 60 | high | 2 | 2 | 2 | 2 | 11 | 0 | 236 | 247 |
| 70 | high | 2 | 2 | 2 | 2 | 11 | 0 | 244 | 250 |
| 80 | high | 2 | 2 | 2 | 2 | 10 | 0 | 234 | 249 |
| 90 | high | 2 | 2 | 2 | 2 | 10 | 0 | 237 | 249 |
| 100 | high | 2 | 2 | 2 | 2 | 11 | 0 | 226 | 254 |
| 110 | high | 2 | 2 | 2 | 2 | 11 | 0 | 244 | 314 |
| 120 | high | 2 | 2 | 2 | 2 | 11 | 0 | 244 | 263 |
| 130 | high | 2 | 2 | 2 | 2 | 10 | 0 | 232 | 250 |
| 140 | high | 2 | 2 | 2 | 2 | 11 | 0 | 246 | 293 |
| 150 | high | 2 | 2 | 2 | 2 | 11 | 0 | 244 | 290 |
| 160 | high | 2 | 2 | 2 | 2 | 11 | 0 | 249 | 273 |
| 170 | idle2 | 2 | 2 | 2 | 1 | 0 | 0 | - | - |
| 180 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 162 sent, 162 ok, 0 errors

events:

    {"t": "2026-11-03T07:44:04.408-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:44:24.429-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:44:56.018-05:00", "rel_s": 51.61, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 81, "averageValue": "3272m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:44:56.018-05:00", "rel_s": 51.61, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-6cvlz", "created": "2026-11-03T12:44:55Z"}
    {"t": "2026-11-03T07:44:58.982-05:00", "rel_s": 54.58, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-6cvlz"}
    {"t": "2026-11-03T07:46:55.894-05:00", "rel_s": 171.49, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:48:26.194-05:00", "rel_s": 261.79, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:48:26.195-05:00", "rel_s": 261.79, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-6cvlz"}
    {"t": "2026-11-03T07:48:47.002-05:00", "rel_s": 282.59, "event": "run_end", "phase": "idle2", "settled": true}
