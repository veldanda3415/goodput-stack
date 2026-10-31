# HTTP vs offline at 384 users, and a replay of the old 64-user sweep point (Kaggle T4, real)

Follow-up F1 to the ridge work ([ridge.md](ridge.md)). Questions: (a) what does serving through `vllm serve` + a
Python HTTP client cost against the offline engine ceiling at 384 sequences, and (b) was the old 615 output tok/s at
64 users (run 20261014-220946_sweep) limited by the GPU or by the client?

## Predictions (written before the F1 run, verbatim from the assignment)

- F1a HTTP at 384 users, same settings as offline: output 1,100–1,400 tok/s, below the offline 1,459; client CPU the likely limiter on 4 vCPUs.
- F1b replay of the old sweep point (64 users, prompt 256 / output 128 ± 25 %, max-num-batched-tokens 2,048): output within ±10 % of 615 tok/s, util.gpu ≈ 100 %, client CPU well below saturation → the old number was GPU-limited.
- F1c same as F1b with max-num-batched-tokens 8,192: small change (< 10 %).
