# Queue depth (KEDA) vs CPU utilisation (HPA) autoscaling on llamacpp-pool (real CPU (laptop))

Build 17, Task A. Question: on the same pool and the same load, does scaling on queue depth (KEDA, current config) give
better user latency per replica-second than the standard HPA scaling on CPU utilisation?

## Predictions (written 2026-11-03 before any run; verbatim from the assignment, not edited afterwards)

- Light load: KEDA stays at 1 replica (no queue); CPU-HPA scales up anyway because llama.cpp drives CPU high whenever a
  slot is busy → more replica-seconds for no TTFT gain.
- Heavy load: both scale out; CPU-HPA reacts no faster than KEDA and cannot tell 1 from 10 waiting requests; TTFT p95
  during the first 60 s similar or worse for CPU-HPA.
- 80 % target scales later than 50 % under heavy load.
- Scale-down timing set by the matched stabilization windows, not the signal.
