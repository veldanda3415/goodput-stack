**8B on 256 GPUs** (TP 1 · PP 1 · DP 256 · EP 1; seq 8,192, 1 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| DP | all-reduce (gradients) | 256 | both (NVLink + scale-out) | 1 | 28.000 | 3.875 | 174.98 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 993.47 |
| **step** | compute + exposed comm |  |  |  |  |  | 1,168.45 |

**70B on 256 GPUs** (TP 8 · PP 4 · DP 8 · EP 1; seq 8,192, 16 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| TP | all-reduce (activations) | 8 | scale-up (NVLink) | 1,280 | 300.648 | 0 | 853.05 |
| PP | send/recv (activations) | 4 | scale-out (backend) | 32 | 0 | 4.295 | 107.53 |
| DP | all-reduce (gradients) | 8 | scale-out (backend) | 1 | 0 | 7.656 | 191.48 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 4,346.44 |
| **step** | compute + exposed comm |  |  |  |  |  | 5,498.50 |

**405B on 2,048 GPUs** (TP 8 · PP 16 · DP 16 · EP 1; seq 8,192, 32 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| TP | all-reduce (activations) | 8 | scale-up (NVLink) | 896 | 420.907 | 0 | 1,181.73 |
| PP | send/recv (activations) | 16 | scale-out (backend) | 64 | 0 | 17.180 | 429.82 |
| DP | all-reduce (gradients) | 16 | scale-out (backend) | 1 | 0 | 11.865 | 296.78 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 12,573.62 |
| **step** | compute + exposed comm |  |  |  |  |  | 14,481.95 |

**Mixtral 8x7B on 256 GPUs** (TP 2 · PP 1 · DP 128 · EP 8; seq 4,096, 1 microbatch(es)) — CALCULATED

| Par. | Collective | Group | Network | Calls/step | Scale-up GB/GPU/step | Scale-out GB/GPU/step | Time/step (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| TP | all-reduce (activations) | 2 | scale-up (NVLink) | 128 | 4.295 | 0 | 12.19 |
| EP | all-to-all (tokens) | 8 | both (NVLink + scale-out) | 128 | 3.221 | 4.295 | 120.80 |
| DP | all-reduce (gradients) | 128 | both (NVLink + scale-out) | 1 | 70.500 | 22.766 | 765.29 |
| **compute** | 6·P·tokens / (GPUs·peak·MFU) |  |  |  |  |  | 403.60 |
| **step** | compute + exposed comm |  |  |  |  |  | 1,301.88 |

**One link at 50% rate in the inter-node ring — 8B on 256 GPUs** — CALCULATED

| Quantity | All links healthy (ms) | One slow link (ms) | Change |
|---|---:|---:|---:|
| DP gradient all-reduce | 174.98 | 271.85 | +55.4% |
| Step (compute + exposed comm) | 1,168.45 | 1,265.32 | +8.3% |

**Prefill → decode KV-cache transfer** — CALCULATED

| Model | KV B/token | Prompt tokens | KV MB/request | Requests/s | Scale-out Gb/s needed | 400G NICs @ 80% | One request on one NIC (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| llama3.2-3b | 114,688 | 2,048 | 234.9 | 10 | 18.8 | 1 | 5.87 |
| llama3-8b | 131,072 | 4,096 | 536.9 | 20 | 85.9 | 1 | 13.42 |
| llama3-70b | 327,680 | 4,096 | 1,342.2 | 20 | 214.7 | 1 | 33.55 |
| llama3-70b | 327,680 | 32,768 | 10,737.4 | 5 | 429.5 | 2 | 268.44 |
