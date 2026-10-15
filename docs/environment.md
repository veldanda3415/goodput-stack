# Environments and pinned versions

Every version here was read from a recorded run (file linked), not from documentation.

## GPU: Kaggle T4 (engine track)

| Component | Version | Where it was read |
|---|---|---|
| GPU | 2 × Tesla T4, 15360 MiB each, sm_75 (one used: `CUDA_VISIBLE_DEVICES=0`) | [smoke env.json](../benchmarks/results/t4/20261014-213711_smoke/results/smoke/env.json) |
| NVIDIA driver | 580.178.04 | `nvidia-smi --query-gpu=driver_version` (same file) |
| CUDA (driver max) | 13.0 | `nvidia-smi` header (same file) |
| OS / Python | Ubuntu 24.04.1 LTS / 3.13.15 | [smoke host.txt](../benchmarks/results/t4/20261014-213711_smoke/results/smoke/logs/host.txt), env.json |
| Host | 4 vCPU, 31 GiB RAM, 20 GiB /kaggle/working | host.txt |
| Kaggle image torch (before vLLM) | 2.11.0+cu128 | smoke env.json |
| **vLLM** | **0.31.0** (latest at the time; first version tried; serves on sm_75 with `TRITON_ATTN`) | [baseline run 2 `attempt-0.31.0`](../benchmarks/results/t4/20261014-215653_baseline/results/baseline/baseline.jsonl) |
| torch (installed by vLLM 0.31.0) | 2.13.0+cu130 | same row, `torch_after_install` |
| DCGM | not available (no `dcgmi`, `nv-hostengine`, `libdcgm*`) | [smoke dcgm.txt](../benchmarks/results/t4/20261014-213711_smoke/results/smoke/logs/dcgm.txt) |
| NVML binding | nvidia-ml-py 13.610.43 (preinstalled) | smoke env.json |
| llama.cpp (CUDA) | b11146 prebuilt `llama-b11146-bin-ubuntu-cuda-12.8-x64` + cudart bundle (same tag as the CPU lab image) | quant stage `llamacpp-install` row |
| lm-eval | 0.4.12 (one release before 0.4.13), own venv, `local-completions` | quant stage `*-lmeval` rows |
| Kaggle CLI (local) | 2.2.3 (one release before 2.2.4) | `.venv/bin/kaggle --version` |

Install note: Kaggle preinstalls torchaudio/torchcodec/torchvision built for its cu128 torch. `pip install vllm`
replaces torch with a cu130 build, after which `import vllm` fails with *"PyTorch and TorchAudio were compiled with
different CUDA versions"* (baseline run 1, every version 0.31.0 → 0.28.0). The notebook uninstalls those three
packages before installing vLLM ([t4_notebook.py](../benchmarks/kaggle/t4_notebook.py) `pip_install_vllm`).

Version choice: the repo rule is "one release behind latest", but the T4 brief said to start from the latest
vLLM and step back only on failure. 0.31.0 worked, so it is pinned. Re-check 0.30.0 if 0.31.0 shows regressions.

## Models

| Role | Repo | Revision | Note |
|---|---|---|---|
| 3B baseline, sweep (predicted model) | `meta-llama/Llama-3.2-3B-Instruct` | `0cb88a4f764b7a12671c53f0838cd831a0843b95` | gated; needs the `HF_TOKEN` Kaggle secret (read via `www.kaggle.com`, see the T4 README) |
| 3B baseline, sweep, FP16 (first round) | `Qwen/Qwen2.5-3B-Instruct` | `aa8e72537993ba99e69dfaafa59ed015b17504d1` | **substitute** used while the secret could not be read |
| 3B AWQ INT4 | `Qwen/Qwen2.5-3B-Instruct-AWQ` | `3559b226e8ce77211e2c1bd7ddfb7686fec4d6dd` | official Qwen |
| 3B GGUF Q8_0 / Q4_K_M | `Qwen/Qwen2.5-3B-Instruct-GGUF` | `7dabda4d13d513e3e842b20f0d435c732f172cbe` | official Qwen |
| 8B AWQ INT4 (KV grid) | `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4` | `db1f81ad4b8c7e39777509fac66c652eb0a52f91` | ungated |

Revisions are the `model_info().sha` recorded in each result row at run time.

## Local lab

See the top-level [README](../README.md#environment): k3s on WSL2, i7-10700, CPU only.
