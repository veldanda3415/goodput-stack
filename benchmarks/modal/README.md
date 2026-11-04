# benchmarks/modal — one H100 SXM on Modal

The H100 build (results: [../results/h100/h100.md](../results/h100/h100.md)) runs on Modal: serverless GPUs, billed per
second of container time (GPU + requested CPU + requested memory).

| file | what |
|---|---|
| [h100_app.py](h100_app.py) | Modal app `goodput-h100`: the image (CUDA 13.0.2 devel + Python 3.12 + vLLM 0.31.0, nsight-systems / DCGM if the CUDA apt repo has them), two volumes, one GPU function per task (`h0` … `h5`, `gpu="H100!"`, 8 vCPU / 32 GiB, explicit timeouts) and a CPU-only `download` |
| [h100_tasks.py](h100_tasks.py) | runs inside the container: H0 smoke + permissions, H1 microbench, H2–H4 offline sweeps / ablations / profiles, H5 served load. Reuses [../kaggle/t4_notebook.py](../kaggle/t4_notebook.py) (offline_point, probe_tools, VllmServer, http_run, samplers) |

```bash
# from the repo root, with the modal CLI already set up (`modal setup`) and a Modal secret `huggingface` (HF_TOKEN)
modal run benchmarks/modal/h100_app.py::download                         # CPU only; weights -> goodput-hf-cache
modal run --detach benchmarks/modal/h100_app.py::task --name h0 --args "--budget-h 0.1"
modal app logs <app-id>                                                  # follow a detached run
modal volume get goodput-h100-results <run_id> benchmarks/results/h100/raw/
modal app list                                                           # nothing of ours may stay running
modal billing report --for today -r h --json                             # spend per app (hourly buckets)
```

Rules the app follows:
- `gpu="H100!"`: the `!` stops Modal from silently upgrading to an H200. The first thing every GPU container does is
  `nvidia-smi -q`; any product name without "H100" writes `ABORTED.txt` and returns before any work.
- Every function has an explicit `timeout`, `retries=0`, `max_containers=1`; no `modal deploy`, no web endpoints, no
  `min_containers` / keep-warm.
- Weights are downloaded once by the CPU-only `download` function into the `goodput-hf-cache` volume (`HF_HOME=/hf`);
  the commit sha of every model is recorded in `/hf/revisions.json` and on every result row. vLLM's compile cache
  (`VLLM_CACHE_ROOT`) is on the same volume, so later containers reuse torch.compile artifacts.
- Results go to the `goodput-h100-results` volume under `<run_id>/<task>/` (committed every 60 s and at exit).
- The repo's `benchmarks/` is mounted at container start (not baked into the image): a code change needs no rebuild.
