# deploy/

Helm chart for the backends (llama.cpp, vLLM simulator) and the Gateway (agentgateway); values files per environment. The EPPs are separate llm-d releases ([gateway/](gateway/)). Models are fetched at deploy time, never baked into images.

```bash
make deploy ENV=k3s      # lint -> diff -> confirm -> upgrade -> helm test (see "Upgrade flow")
make deploy-test         # helm test only: llama.cpp + simulator sanity pods
```

## Environments (values files)

| File | What it holds |
|---|---|
| [values.yaml](charts/inference/values.yaml) | **shared defaults**: images, server flags, simulator config and calibration, probes, resources, NetworkPolicy |
| [values-k3s.yaml](charts/inference/values-k3s.yaml) | single-node k3s on WSL2, context `default`: 1 replica each, model on a local-path **PVC** |
| [values-k3d.yaml](charts/inference/values-k3d.yaml) | multi-node k3d on Podman, context `k3d-goodput`: llama.cpp ×2, sim ×3, **spread across nodes**, model on a **hostPath** mounted into every node |

Always both files, shared first: `-f values.yaml -f values-<env>.yaml` (the release script does this).
An env file holds only what differs per cluster; if a value is the same everywhere it belongs in values.yaml.

Why the PVC can't go to k3d: local-path volumes are ReadWriteOnce **and** pinned to the node that
created them, so a llama.cpp replica scheduled on a second node can never mount the model. k3d
instead mounts the host's `~/models` into every node container, and the pods use it as a hostPath.

### k3d multi-node (once)

```bash
systemctl --user start podman.socket                 # k3d talks to Podman through the Docker API socket
export DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock
mkdir -p ~/models && cp -L ~/.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct-GGUF/snapshots/*/qwen2.5-0.5b-instruct-q4_k_m.gguf ~/models/
k3d cluster create goodput --agents 3 -v "$HOME/models:/var/lib/goodput/models@all"
k3d image import localhost/llama-server:b11146 -c goodput    # pullPolicy: Never -> must be on every node
make deploy ENV=k3d
```

`cp -L` copies the real file: the HF cache entry is a symlink into `../../blobs`, which would dangle
inside the pod. On k3d every node reports all 16 host threads, so CPU requests don't protect the
real cores: keep llama.cpp at 2 replicas × 4 threads. The host is not a node there, so benchmarks
need a port-forward (`--set server.base_url=http://127.0.0.1:18000`), and `bringup_timing.sh`
(1 replica only) applies to k3s. **Not yet run on k3d** (no cluster yet): the k3d values are lint-clean
and accepted by the API server in a dry run, nothing more.

## Upgrade flow

```bash
make deploy-diff ENV=k3s        # 1. what would change on the live cluster ("no changes" if nothing)
make deploy ENV=k3s             # 2. lint -> diff -> [y/N] -> upgrade -> helm test
```

[release.sh](release.sh) steps (also callable one by one: `deploy/release.sh lint|diff|upgrade|test <env>`):

1. **lint**: `helm lint` with both values files (offline).
2. **diff**: live cluster vs this checkout.
   - With the [helm-diff](https://github.com/databus23/helm-diff) plugin installed:
     `helm diff upgrade` (also shows hooks and deletions natively).
   - Without it: `helm template ... | kubectl diff --server-side --field-manager=helm`.
     That is the same server-side apply Helm 4 performs, so defaulted fields don't show up
     as noise. Helm's ownership annotations are added to the render first. Objects the upgrade
     would **delete** are listed separately (`WOULD DELETE Kind/name`); kubectl diff can't see those.
3. **confirm**, unless `--yes` (`make deploy ARGS=--yes`).
4. **upgrade**: `helm upgrade --install --wait --rollback-on-failure`. Waits until every Deployment
   is rolled out; if that fails, Helm rolls back to the last good revision. Prints the last 3 revisions.
5. **test**: `helm test --logs`. The sanity pods hit both Services through the NetworkPolicy.

Every helm/kubectl call names the env's kube context (`default` / `k3d-goodput`, override with
`KUBE_CONTEXT=`), so k3d values can't reach the k3s cluster just because it is the current context.
Server-side field ownership: anything that patches release objects by hand must hand ownership
back, or the next upgrade fails with a conflict. The benchmark harness does
(`benchmarks/engine/k8s.py`, field manager `goodput-bench`).

Verified on k3s (2026-10-02):
- the values split renders identically ("no changes")
- disabling the sim shows 4 `WOULD DELETE`
- the full flow went through as revision 21, helm tests passed, no pod restarted

| Backend | Objects (release `inf`) | Pool label | Port | Measures |
|---|---|---|---|---|
| llama.cpp (CPU) | `inf-llamacpp` Deployment/Service/NetworkPolicy/PVC | `goodput-stack/pool: cpu` | 8080 | real |
| vLLM simulator | `inf-vllm-sim` Deployment/Service/NetworkPolicy/ConfigMap | `goodput-stack/pool: sim` | 8000 | **simulated** |

Both serve the same model name (`qwen2.5-0.5b-instruct`), so the gateway sees one model behind two InferencePools.

## vLLM simulator (`sim:` in values.yaml)

[llm-d-inference-sim](https://github.com/llm-d/llm-d-inference-sim) **v0.10.2** (pinned by digest;
v0.10.2 = last patch of the previous minor, v0.11.x is newer). It speaks vLLM's OpenAI API and
`vllm:*` Prometheus metrics but runs no model: it sleeps for the latency it is configured with.

**Why:** the EPP routing probes, KEDA autoscaling and GPU-scheduling work need many vLLM-shaped backends,
and there is no GPU in the cluster. One sim pod uses ~6 m CPU and ~10 MiB, so dozens fit on the
workstation. It also gives repeatable latency, failure injection and a fake model-load time.
**Not for:** engine performance numbers. Anything measured against it is labelled simulated
(pod label `goodput-stack/simulated: "true"`, results under `benchmarks/results/sim/`).

- **Config:** `sim.config` is rendered into a ConfigMap and passed as `--config`; keys are the
  simulator's flag names (`podman run --rm ghcr.io/llm-d/llm-d-inference-sim:v0.10.2 --help`).
  A config change rolls the pods (checksum annotation).
- **Calibration:** latency is fitted to the real llama.cpp runs of 2026-09-30: TTFT = 15 ms +
  2.4 ms × prompt tokens, ITL 16.3 ms configured (≈ 15.6 ms delivered), `max-num-seqs` 2 (= llama.cpp `-np 2`). Matches llama.cpp
  within ~5 % up to 512-token prompts; longer prompts are super-linear on the CPU and the linear
  model is up to 24 % fast at 4096 tokens. Comments in values.yaml give the sources.
- **Tokenizer:** `force-dummy-tokenizer: true`. With a real HF model name the simulator would
  otherwise send every tokenization to a separate vLLM "render" service. Dummy = offline,
  ~1 token per word.
- **Load factor race (upstream, v0.10.2 and v0.11.2):** `time-factor-under-load` F scales
  latency by `1 + (F-1)(running-1)/(max-num-seqs-1)`, but prefill reads `running` from an
  asynchronously updated counter, usually before the new request is counted. With F > 1 an idle
  server then prefills too fast (×0.15 at F = 1.85, `max-num-seqs` 2), and sometimes it doesn't
  (non-deterministic; long prompts more often get the right count). **Decision (2026-10-02): F = 1.0**:
  exact latency, but no slowdown under load (2 running requests decode at 15.6 ms, llama.cpp
  needs 28.9 ms); queueing still via `max-num-seqs`. A patched image is deferred; real loaded
  numbers will come from vLLM on a T4. Benchmark experiments that need a slowdown set F themselves.
- **What no setting can express:** a long prefill slowing others' decode, decode slowing with
  context length, super-linear prefill, KV-memory-limited admission, and the fact that load hurts
  decode (×10 at 16 running on llama.cpp) far more than prefill (×1.4). The sim applies one factor
  to both, so with F = 10.1 its TTFT at 16 clients is 6 s vs 0.84 s on llama.cpp.
- **Probes:** startup/readiness on `/health/ready` (503 while `startup-duration` runs, so a model
  load can be faked), liveness on TCP like llama.cpp.
- **Hardening:** non-root (65532), read-only root filesystem, all capabilities dropped. No CPU
  limit: CFS throttling would show up as fake ITL spikes.
- **NetworkPolicy:** same `networkPolicy.allowFrom` as llama.cpp (gateway proxy, EPPs and `helm test` pods),
  rendered by one shared helper. The k3s node itself is let through by kube-router, which is how
  the benchmark harness reaches the ClusterIP from the host.
