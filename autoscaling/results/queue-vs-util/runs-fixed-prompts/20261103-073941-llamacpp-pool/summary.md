# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 2 --max-tokens 64 --idle 20 --high 150 --tail 300 --fixed-prompts --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T07:39:42.211-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 2 | 12 | 0 | 230 | 250 |
| 30 | high | 1 | 1 | 1 | 2 | 10 | 0 | 224 | 239 |
| 40 | high | 1 | 1 | 1 | 2 | 10 | 0 | 228 | 235 |
| 50 | high | 1 | 1 | 1 | 2 | 10 | 0 | 244 | 262 |
| 60 | high | 1 | 1 | 1 | 2 | 11 | 0 | 236 | 270 |
| 70 | high | 1 | 1 | 1 | 2 | 11 | 0 | 238 | 271 |
| 80 | high | 1 | 1 | 1 | 2 | 11 | 0 | 232 | 249 |
| 90 | high | 1 | 1 | 1 | 2 | 11 | 0 | 228 | 243 |
| 100 | high | 1 | 1 | 1 | 2 | 12 | 0 | 239 | 251 |
| 110 | high | 1 | 1 | 1 | 2 | 11 | 0 | 247 | 263 |
| 120 | high | 1 | 1 | 1 | 2 | 11 | 0 | 233 | 248 |
| 130 | high | 1 | 1 | 1 | 2 | 11 | 0 | 239 | 255 |
| 140 | high | 1 | 1 | 1 | 2 | 11 | 0 | 233 | 258 |
| 150 | high | 1 | 1 | 1 | 2 | 10 | 0 | 244 | 253 |
| 160 | high | 1 | 1 | 1 | 2 | 11 | 0 | 241 | 268 |
| 170 | idle2 | 1 | 1 | 1 | 1 | 0 | 0 | - | - |
| 180 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 163 sent, 163 ok, 0 errors

events:

    {"t": "2026-11-03T07:39:41.742-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 2, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T07:40:01.744-05:00", "rel_s": 20.0, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T07:42:33.020-05:00", "rel_s": 171.28, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T07:42:53.044-05:00", "rel_s": 191.3, "event": "run_end", "phase": "idle2", "settled": true}
