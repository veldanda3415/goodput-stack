"""Modal app for the H100 build: one NVIDIA H100 SXM per task, billed per second (benchmarks/modal/README.md).

    modal run benchmarks/modal/h100_app.py::download                               # CPU only: weights -> volume
    modal run --detach benchmarks/modal/h100_app.py::task --name h0                # H0 smoke + permissions
    modal run --detach benchmarks/modal/h100_app.py::task --name h2 --args "--budget-h 1.0"

Every GPU function requests `gpu="H100!"` (the `!` stops Modal from upgrading to an H200), has an explicit timeout, and
runs `python -m benchmarks.modal.h100_tasks --task <name>` from the repo's benchmarks/ (mounted at container start, so
a code change needs no image rebuild). Results go to the `goodput-h100-results` volume under <run_id>/ and are pulled
back with `modal volume get goodput-h100-results <run_id> benchmarks/results/h100/raw/`.
Weights: the `goodput-hf-cache` volume at /hf (HF_HOME). No deploy, no web endpoints, no warm containers.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parents[2] if modal.is_local() else Path("/root")   # the container sees /root/h100_app.py
APP_NAME = "goodput-h100"
VLLM_VERSION = "0.31.0"
CUDA_IMAGE = "nvidia/cuda:13.0.2-devel-ubuntu24.04"

# nsight-systems and DCGM are not in the CUDA devel image; try the CUDA apt repo the image already has. A failure is a
# result (recorded by H0 as "not installed"), not a build error.
TOOLS_SH = [   # one RUN line each; `|| true` / `; true` so a missing package never fails the build
    "apt-get update -q > /dev/null; true",
    "NSYS=$(apt-cache search --names-only '^nsight-systems-[0-9]' | awk '{print $1}' | sort -V | tail -1); echo nsys candidate: $NSYS; "
    "[ -n \"$NSYS\" ] && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $NSYS > /tmp/nsys-apt.log 2>&1; "
    "echo nsys apt rc=$?; tail -3 /tmp/nsys-apt.log; true",
    "DCGM=$(apt-cache search --names-only '^datacenter-gpu-manager-4-cuda13' | awk '{print $1}' | head -1); echo dcgm candidate: $DCGM; "
    "[ -n \"$DCGM\" ] && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $DCGM > /tmp/dcgm-apt.log 2>&1; "
    "echo dcgm apt rc=$?; tail -3 /tmp/dcgm-apt.log; true",
    "ls /opt/nvidia/nsight-systems*/bin/nsys /usr/local/bin/nsys /usr/bin/nsys /usr/bin/dcgmi /usr/local/cuda/bin/ncu 2>/dev/null; true",
]

image = (
    modal.Image.from_registry(CUDA_IMAGE, add_python="3.12")
    .apt_install("pciutils", "procps", "util-linux", "numactl")
    .run_commands(*TOOLS_SH)
    .uv_pip_install(f"vllm=={VLLM_VERSION}")
    .env({"HF_HOME": "/hf", "HF_HUB_CACHE": "/hf/hub", "VLLM_CACHE_ROOT": "/hf/vllm-cache", "PYTHONUNBUFFERED": "1",
          "TOKENIZERS_PARALLELISM": "false"})
    .add_local_dir(REPO / "benchmarks", "/root/src/benchmarks",
                   ignore=["results", "**/__pycache__", "**/*.pyc"])
)

hf_vol = modal.Volume.from_name("goodput-hf-cache", create_if_missing=True)
res_vol = modal.Volume.from_name("goodput-h100-results", create_if_missing=True)
app = modal.App(APP_NAME, image=image)
GPU_KW = dict(gpu="H100!", cpu=8.0, memory=32768, volumes={"/hf": hf_vol, "/results": res_vol},
              secrets=[modal.Secret.from_name("huggingface")], retries=0, max_containers=1)
# per-task container timeouts (s): the task budget plus room for the image pull / start and the final writes
TIMEOUTS = {"h0": 25 * 60, "h1": 30 * 60, "h2": 80 * 60, "h3": 110 * 60, "h4": 55 * 60, "h5": 50 * 60}


def _run(name: str, args: str, git_sha: str, run_id: str, t_call: float) -> dict:
    """Run the task module in a subprocess (its own process group) and commit the results volume every 60 s."""
    t0 = time.time()
    out = Path("/results") / run_id
    out.mkdir(parents=True, exist_ok=True)
    # first: which GPU did we get? Anything but an H100 aborts the task (an H200 would invalidate the comparison)
    q = subprocess.run(["nvidia-smi", "-q"], capture_output=True, text=True)
    (out / "nvidia-smi-q-first.txt").write_text(f"# t_unix={time.time():.3f} rc={q.returncode}\n{q.stdout}{q.stderr}")
    names = [l.split(":", 1)[1].strip() for l in q.stdout.splitlines() if l.strip().startswith("Product Name")]
    if not names or not all("H100" in n for n in names):
        (out / "ABORTED.txt").write_text(f"GPU is not an H100: {names}\n")
        res_vol.commit()
        return {"run_id": run_id, "rc": "aborted", "gpu_names": names}
    (out / "container_start.txt").write_text(
        f"t_local_call_unix={t_call:.3f}\nt_container_fn_start_unix={t0:.3f}\n"
        f"call_to_fn_start_s={t0 - t_call:.1f}\n" + "".join(f"{k}={v}\n" for k, v in sorted(os.environ.items())
                                                             if k.startswith("MODAL_") and "TOKEN" not in k and "SECRET" not in k))
    # FLASHINFER_WORKSPACE_BASE (flashinfer/jit/env.py, 0.7.0.post1): its JIT modules (the sampler took ~75 s to build
    # in H0) go to the volume, so later containers reuse them
    env = dict(os.environ, PYTHONPATH="/root/src", GOODPUT_RESULTS=str(out), GOODPUT_GIT_SHA=git_sha, GOODPUT_RUN_ID=run_id,
               GOODPUT_SESSION_T0=repr(t0), FLASHINFER_WORKSPACE_BASE="/hf/flashinfer-ws")
    stop = threading.Event()

    def committer() -> None:
        while not stop.wait(60):
            try:
                res_vol.commit()
                hf_vol.commit()   # compile / FlashInfer JIT caches survive a stopped container
            except Exception as exc:   # a failed background commit is retried next minute; the final one is checked
                print(f"volume commit failed: {exc!r}", flush=True)

    th = threading.Thread(target=committer, daemon=True)
    th.start()
    cmd = ["python", "-m", "benchmarks.modal.h100_tasks", "--task", name, *args.split()]
    print("$ " + " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd="/root/src", env=env).returncode
    (out / "container_end.txt").write_text(f"rc={rc}\nt_end_unix={time.time():.3f}\nfn_wall_s={time.time() - t0:.1f}\n")
    stop.set()
    th.join(5)
    hf_vol.commit()
    res_vol.commit()
    return {"run_id": run_id, "rc": rc, "fn_wall_s": round(time.time() - t0, 1)}


@app.function(**GPU_KW, timeout=TIMEOUTS["h0"])
def h0(args: str, git_sha: str, run_id: str, t_call: float) -> dict:
    return _run("h0", args, git_sha, run_id, t_call)


@app.function(**GPU_KW, timeout=TIMEOUTS["h1"])
def h1(args: str, git_sha: str, run_id: str, t_call: float) -> dict:
    return _run("h1", args, git_sha, run_id, t_call)


@app.function(**GPU_KW, timeout=TIMEOUTS["h2"])
def h2(args: str, git_sha: str, run_id: str, t_call: float) -> dict:
    return _run("h2", args, git_sha, run_id, t_call)


@app.function(**GPU_KW, timeout=TIMEOUTS["h3"])
def h3(args: str, git_sha: str, run_id: str, t_call: float) -> dict:
    return _run("h3", args, git_sha, run_id, t_call)


@app.function(**GPU_KW, timeout=TIMEOUTS["h4"])
def h4(args: str, git_sha: str, run_id: str, t_call: float) -> dict:
    return _run("h4", args, git_sha, run_id, t_call)


@app.function(**(GPU_KW | {"cpu": 16.0}), timeout=TIMEOUTS["h5"])
def h5(args: str, git_sha: str, run_id: str, t_call: float) -> dict:
    """H5 runs the HTTP client in the same container as `vllm serve`, so it gets 16 vCPUs instead of 8."""
    return _run("h5", args, git_sha, run_id, t_call)


DOWNLOADS = {   # repo -> revision ("main" = resolve the current commit once and record it)
    "Qwen/Qwen2.5-3B-Instruct": "aa8e72537993ba99e69dfaafa59ed015b17504d1",
    "meta-llama/Llama-3.1-8B-Instruct": "main",
    "RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8": "main",
}


@app.function(cpu=4.0, memory=8192, volumes={"/hf": hf_vol}, secrets=[modal.Secret.from_name("huggingface")],
              timeout=45 * 60, retries=0, max_containers=1)
def download() -> dict:
    """CPU-only: weights + config of every model into the hf-cache volume; /hf/revisions.json records each commit."""
    import json
    from huggingface_hub import HfApi, snapshot_download
    api = HfApi()
    revs_path = Path("/hf/revisions.json")
    revs = json.loads(revs_path.read_text()) if revs_path.exists() else {}
    for repo, rev in DOWNLOADS.items():
        t0 = time.time()
        info = api.model_info(repo, revision=rev if rev != "main" else None)
        sha = revs.get(repo, {}).get("revision") or info.sha
        path = snapshot_download(repo, revision=sha, ignore_patterns=["original/*", "*.pth", "*.gguf"])
        size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
        revs[repo] = {"revision": sha, "path": path, "bytes": size, "download_s": round(time.time() - t0, 1),
                      "last_modified": str(getattr(info, "last_modified", "")), "resolved_at_unix": round(time.time(), 1)}
        print(repo, revs[repo], flush=True)
        revs_path.write_text(json.dumps(revs, indent=2) + "\n")
        hf_vol.commit()
    return revs


def _git_sha() -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, capture_output=True,
                           text=True).stdout.strip()
    return sha + ("-dirty" if dirty else "")


@app.local_entrypoint()
def task(name: str, args: str = "") -> None:
    fn = {"h0": h0, "h1": h1, "h2": h2, "h3": h3, "h4": h4, "h5": h5}[name]
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}_{name}"
    print(f"run_id={run_id} git={_git_sha()} app={APP_NAME}", flush=True)
    print(fn.remote(args, _git_sha(), run_id, time.time()), flush=True)
