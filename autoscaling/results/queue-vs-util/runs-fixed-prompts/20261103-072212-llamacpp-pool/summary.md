# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090 --hpa inf-llamacpp-cpu`  started 2026-11-03T07:22:13.325-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 12 | 0 | 223 | 237 |
| 30 | high | 1 | 1 | 1 | 2 | 11 | 0 | 225 | 254 |
| 40 | high | 1 | 1 | 1 | 2 | 10 | 0 | 229 | 244 |
| 50 | high | 1 | 1 | 1 | 2 | 12 | 0 | 238 | 255 |
| 60 | high | 1 | 1 | 1 | 2 | 11 | 0 | 235 | 267 |
| 70 | high | 2 | 2 | 2 | 2 | 10 | 0 | 259 | 317 |
| 80 | high | 2 | 2 | 2 | 2 | 10 | 0 | 318 | 336 |
| 90 | high | 2 | 2 | 2 | 2 | 10 | 0 | 330 | 429 |
| 100 | high | 2 | 2 | 2 | 2 | 10 | 0 | 297 | 425 |
| 110 | high | 2 | 2 | 2 | 2 | 10 | 0 | 309 | 370 |
| 120 | high | 2 | 2 | 2 | 2 | 10 | 0 | 257 | 307 |
| 130 | high | 2 | 2 | 2 | 2 | 10 | 0 | 279 | 400 |
| 140 | high | 2 | 2 | 2 | 2 | 10 | 0 | 285 | 443 |
| 150 | high | 2 | 2 | 2 | 2 | 10 | 0 | 308 | 469 |
| 160 | high | 2 | 2 | 2 | 2 | 11 | 0 | 262 | 320 |
| 170 | idle2 | 2 | 2 | 2 | 2 | 0 | 0 | - | - |
| 180 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 157 sent, 157 ok, 0 errors

events:

    {"t": "2026-11-03T07:22:12.718-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:22:32.738-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:23:26.326-05:00", "rel_s": 73.61, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 2, "hpa_metric": [{"resource": {"current": {"averageUtilization": 100, "averageValue": "4010m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:23:26.327-05:00", "rel_s": 73.61, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-kc99g", "created": "2026-11-03T12:23:25Z"}
    {"t": "2026-11-03T07:23:29.343-05:00", "rel_s": 76.63, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-kc99g"}
    {"t": "2026-11-03T07:23:31.437-05:00", "rel_s": 78.72, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-kc99g"}
    {"t": "2026-11-03T07:25:04.202-05:00", "rel_s": 171.49, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:26:11.142-05:00", "rel_s": 238.43, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"resource": {"current": {"averageUtilization": 0, "averageValue": "10m"}, "name": "cpu"}, "type": "Resource"}]}
    {"t": "2026-11-03T07:26:11.144-05:00", "rel_s": 238.43, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-kc99g"}
    {"t": "2026-11-03T07:26:31.293-05:00", "rel_s": 258.58, "event": "run_end", "phase": "idle2", "settled": true}
