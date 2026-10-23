# P8 on real llama.cpp — size-blind routing, CPU-pinned replicas

**Label: workstation CPU (WSL2), real llama.cpp, real gateway + EPP; 4 pinned CPUs per replica.** Rows sent straight
to a pod (interference sets, "forced to L / S") are labelled **direct to pod, not routed through the EPP**.

Question (GAPS.md P8, #23): with two real llama.cpp replicas, one holding 2 long prompts (L) and one holding 3 short
ones (S), which pod does the stock EPP pick for a short probe, and what does the probe pay? Same with the upstream
token-load-scorer. And how much do two replicas on one CPU slow each other down, unpinned vs pinned by the kubelet
static CPU manager?

Status: in progress. Sections are filled in the order they were run; every prediction was written before its run.

## Task 0 — baseline and topology (2026-10-23, no changes)

| | value | source |
|---|---|---|
| Host | i7-10700 (WSL2 guest, kernel 6.18.33.2-microsoft-standard-WSL2), `nproc` 16 | `nproc`, `uname -r` |
| Topology (guest view) | 1 socket, 8 cores, 2 threads each; siblings are `2k,2k+1` (cpu0: 0-1 … cpu15: 14-15); one shared L3 | `lscpu -e`, `/sys/devices/system/cpu/cpu*/topology/thread_siblings_list` |
| k3s | v1.36.2+k3s1 (01b6f04a), single node `ravi-home` | `k3s --version`, `kubectl get nodes` |
| `/etc/rancher/k3s/config.yaml` | `kubelet-arg: [container-log-max-size=10Mi, container-log-max-files=5]`, `disable: [traefik]` (sha256 `3609cf7f…`) | `cat` (file is 0644) |
| kubelet flags | `--config-dir=/var/lib/rancher/k3s/agent/etc/kubelet.conf.d --container-log-max-files=5 --container-log-max-size=10Mi …`; no `--root-dir`, so root dir = kubelet default `/var/lib/kubelet` | k3s journal line "Running kubelet …" (2026-10-14 06:09:07); default from `kubelet --help` v1.36.2 |
| CPU manager | `cpuManagerPolicy: none`, options none, `reservedSystemCPUs` none, `cpuCFSQuota: true`, period 100ms | `kubectl get --raw /api/v1/nodes/ravi-home/proxy/configz`; journal `cpu_manager.go:235 "Starting" policy="none"` |
| `cpu_manager_state` | `/var/lib/kubelet/cpu_manager_state`: **not readable without root** (Permission denied); journal shows default CPUSet "" and assignments {} | `cat`, journal `state_mem.go:123/141` |
| `helm test inf` | 3/3 Succeeded (gateway, llamacpp, sim sanity) 09:39 EDT | `helm test inf -n inference` |
| One request per pool | cpu (`x-pool: cpu`): 200, 31 prompt / 8 completion tokens, 0.188 s; sim: 200, 0.052 s | `curl` to 192.168.117.204 |
| Host load | loadavg 1.23 → 1.02 over 30 s; CPU 94.7–98.2 % idle; top: k3s-server 12.6 %, sim-pool EPP 6.8 %, prometheus 5.8 % | `top -b -d 5 -n 7`, `/proc/loadavg` |
| Other workloads | namespace `netcortex` (2 pods, another project) and kube-prometheus-stack, KEDA, agentgateway, 2 sim pods | `kubectl get pods -A` |
| sim-pool EPP | running **`token-load.yaml`** (the `make epp-plugin-on` state) — "restore as it was" means token-load on | `kubectl get deploy sim-pool-epp … args`, backup below |

**WSL2 caveat.** The guest's 16 vCPUs are not pinned to physical cores on the Windows side: Hyper-V schedules them
on whatever logical processors it likes. The sibling pairs above are what the guest is told, not a hardware
guarantee. "Pinned" in this file means pinned to guest vCPUs.

Backups of everything changed (helm values of all three releases, EPP ConfigMap data, EPP args, ScaledObject pause
state, the k3s config): `benchmarks/results/probes/p8_cpu/backup/`.

### Flag and option names, and where they came from

- llama-server: `llama-server --help` and `--version` inside the pinned image (`version: 0.5.0-dev (build 11146, commit 7fe450e19)`, GNU 14.2.0).
  `-t/--threads`, `-tb/--threads-batch` (default "same as --threads"), `-c/--ctx-size`, `-np/--parallel`,
  `-kvu/--kv-unified` ("default: enabled if number of slots is auto"), `--cache-prompt/--no-cache-prompt`,
  `-cram/--cache-ram` (default 8192 MiB), `--metrics`.
- Context split in b11146: with an explicit `--parallel 2` the pod log says
  `load_model: initializing, n_slots = 2, n_ctx_slot = 2048, kv_unified = 'false'` at `-c 4096`, so `-c` is divided
  per slot. This run uses `-c 8192` → 4,096 per slot (log: `n_ctx` 4096 per slot in `/slots`).
- kubelet: `kubelet --help` of the official v1.36.2 binary (dl.k8s.io, sha256 verified against the published
  `.sha256`): `--cpu-manager-policy` ('none', 'static'), `--cpu-manager-policy-options`, `--reserved-cpus`,
  `--kube-reserved`, `--cpu-cfs-quota`. `CPUManagerPolicyBetaOptions` (BETA, default true) and
  `CPUManagerPolicyAlphaOptions` (ALPHA, default false) are listed; **`DisableCPUQuotaWithExclusiveCPUs` is not listed**
  in this version's feature-gate help. `k3s` has no `kubelet --help` ("No help topic for 'kubelet'"); `k3s server --help`
  lists `--kubelet-arg`.
- Metrics: `/metrics` of the pod: `llamacpp:requests_processing`, `llamacpp:requests_deferred`, `llamacpp:prompt_tokens_total`, … (no KV metric).

## Setup used in both phases

Overlay `deploy/charts/inference/values-k3s-p8cpu.yaml` on values-k3s.yaml (`OVERLAYS=... deploy/release.sh`,
release revision 34): `-c 8192 --parallel 2 --threads 4 --threads-batch 4 --no-cache-prompt --cache-ram 0 --metrics`,
model `/models/qwen2.5-0.5b-instruct-q4_k_m.gguf` sha256 `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`,
CPU request 4. llama.cpp ScaledObject paused at 2 (`autoscaling.keda.sh/paused-replicas=2`, the method autoscaling/README.md uses).

Client: `scripts/probe_p8_size_blind.py --pool cpu`, from the host (the k3s node) straight to pod IPs (no
port-forward) or to the gateway LB 192.168.117.204 with `x-pool: cpu`. Prompts are P8's `"w0 w1 …"` text cut to
3,000 / 200 / 100 real tokens with the pod's `/tokenize` + `/detokenize`, each with a fresh uuid prefix; with the chat
template the engine reports 3,056 / ~230 / ~160 prompt tokens. Background: closed loop, streamed, `max_tokens` 64,
`ignore_eos`, temperature 0. Probe: streamed, `max_tokens` 32, `ignore_eos`, temperature 0.
TTFT = POST → first chunk with non-empty `delta.content` (`stream_chat`, the repo harness definition).
Per condition: 2 blocks × 6 probes, L/S roles swap between the two physical pods in block 2, idle guard before each
block, the background must hold its in-flight count for 3 s, then each probe goes out after a seeded uniform 0–8 s
delay and ≥ 2 s after the previous one. "Mid-prefill" = at the probe's send time an L background request had been
sent and had not yet returned its first chunk (Build 11's test).

## Calibration (unpinned, one replica, other idle, `/completion` timings)

`benchmarks/results/probes/p8_cpu/calibration-unpinned.jsonl` (09:42 EDT, git 1ccaef8):

| prompt | prompt_n | prefill | prefill tok/s | decode tok/s (64 tokens) |
|---|---|---|---|---|
| long | 3,029 / 3,031 | 13.68 / 13.77 s | 221.4 / 220.1 | 37.6 / 37.2 |
| short | 230 / 228 | 0.87 / 0.86 s | 265.6 / 263.8 | 53.5 / 59.0 |

One long prefill takes ~13.7 s at 4 threads (≤ 60 s), so the long prompt stays at the Build 11 size (3,000 tokens).

## Task 1 — unpinned control (policy `none`, Burstable, no CPU limit)

**Prediction (written before the run, from the calibration only).** Probe on an idle pod, ~160 prompt tokens at
~265 tok/s → TTFT ≈ 0.6 s; decode ≈ 54–59 tok/s (short-context calibration). "Neighbour busy": 8 busy threads on
16 vCPUs with no pinning, so the kernel may put a probe thread on the sibling of a busy one; expected TTFT ≥ alone and
decode ≤ alone. The calibration has no two-pod measurement, so no magnitude is predicted.
