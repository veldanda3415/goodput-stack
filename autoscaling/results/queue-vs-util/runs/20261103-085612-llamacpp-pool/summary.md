# loadgen llamacpp-pool

`/home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/loadgen.py --pool cpu --concurrency 6 --max-tokens 64 --idle 20 --high 150 --tail 300 --out-dir /home/veldanda3415/workspace/goodput-stack-b17-laptop/autoscaling/results/queue-vs-util/runs --prom http://10.43.105.58:9090`  started 2026-11-03T08:56:12.957-05:00

| t (s) | phase | spec | ready | HPA desired | queue max | req sent | errors | client TTFT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 10 | idle | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 20 | high | 1 | 1 | 1 | 6 | 10 | 0 | 6,499 | 7,910 |
| 30 | high | 1 | 1 | 1 | 6 | 8 | 0 | 5,380 | 5,521 |
| 40 | high | 3 | 3 | 3 | 6 | 8 | 0 | 5,586 | 6,786 |
| 50 | high | 3 | 3 | 3 | 6 | 10 | 0 | 646 | 3,714 |
| 60 | high | 3 | 3 | 3 | 6 | 13 | 0 | 858 | 4,078 |
| 70 | high | 3 | 3 | 3 | 6 | 12 | 0 | 634 | 2,518 |
| 80 | high | 3 | 3 | 3 | 6 | 15 | 0 | 699 | 4,815 |
| 90 | high | 3 | 3 | 3 | 6 | 10 | 0 | 662 | 2,925 |
| 100 | high | 3 | 3 | 3 | 6 | 16 | 0 | 847 | 3,748 |
| 110 | high | 3 | 3 | 3 | 6 | 12 | 0 | 643 | 2,517 |
| 120 | high | 3 | 3 | 3 | 6 | 13 | 0 | 656 | 3,045 |
| 130 | high | 3 | 3 | 3 | 6 | 12 | 0 | 2,212 | 3,281 |
| 140 | high | 3 | 3 | 3 | 6 | 13 | 0 | 673 | 3,114 |
| 150 | high | 3 | 3 | 3 | 6 | 14 | 0 | 632 | 3,847 |
| 160 | high | 3 | 3 | 3 | 6 | 14 | 0 | 678 | 2,440 |
| 170 | idle2 | 3 | 3 | 3 | 6 | 0 | 0 | - | - |
| 180 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 190 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 200 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 210 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 220 | idle2 | 3 | 3 | 3 | 0 | 0 | 0 | - | - |
| 230 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 240 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 250 | idle2 | 2 | 2 | 2 | 0 | 0 | 0 | - | - |
| 260 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 270 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |
| 280 | idle2 | 1 | 1 | 1 | 0 | 0 | 0 | - | - |

requests: 180 sent, 180 ok, 0 errors

events:

    {"t": "2026-11-03T08:56:12.404-05:00", "rel_s": 0.0, "event": "run_start", "phase": "idle", "pool": "llamacpp-pool", "deploy": "inf-llamacpp", "concurrency": 6, "max_tokens": 64, "idle": 20.0, "high": 150.0}
    {"t": "2026-11-03T08:56:32.422-05:00", "rel_s": 20.02, "event": "load_start", "phase": "high"}
    {"t": "2026-11-03T08:56:56.259-05:00", "rel_s": 43.86, "event": "hpa_desired_change", "phase": "high", "old": 1, "new": 3, "hpa_metric": [{"external": {"current": {"averageValue": "4167m"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T08:56:57.324-05:00", "rel_s": 44.92, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-kbmp5", "created": "2026-11-03T13:56:56Z"}
    {"t": "2026-11-03T08:56:57.325-05:00", "rel_s": 44.92, "event": "pod_created", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-tncwb", "created": "2026-11-03T13:56:56Z"}
    {"t": "2026-11-03T08:57:00.275-05:00", "rel_s": 47.87, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-kbmp5"}
    {"t": "2026-11-03T08:57:00.277-05:00", "rel_s": 47.87, "event": "pod_ready", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-tncwb"}
    {"t": "2026-11-03T08:57:02.206-05:00", "rel_s": 49.8, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-tncwb"}
    {"t": "2026-11-03T08:57:05.332-05:00", "rel_s": 52.93, "event": "pod_first_served", "phase": "high", "pod": "inf-llamacpp-5d577dcf66-kbmp5"}
    {"t": "2026-11-03T08:59:07.493-05:00", "rel_s": 175.09, "event": "load_stop", "phase": "idle2"}
    {"t": "2026-11-03T09:00:11.316-05:00", "rel_s": 238.91, "event": "hpa_desired_change", "phase": "idle2", "old": 3, "new": 2, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:00:11.317-05:00", "rel_s": 238.92, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-tncwb"}
    {"t": "2026-11-03T09:00:41.180-05:00", "rel_s": 268.78, "event": "hpa_desired_change", "phase": "idle2", "old": 2, "new": 1, "hpa_metric": [{"external": {"current": {"averageValue": "0"}, "metric": {"name": "s0-prometheus", "selector": {"matchLabels": {"scaledobject.keda.sh/name": "inf-llamacpp"}}}}, "type": "External"}]}
    {"t": "2026-11-03T09:00:41.182-05:00", "rel_s": 268.78, "event": "pod_gone", "phase": "idle2", "pod": "inf-llamacpp-5d577dcf66-kbmp5"}
    {"t": "2026-11-03T09:01:01.615-05:00", "rel_s": 289.21, "event": "run_end", "phase": "idle2", "settled": true}
