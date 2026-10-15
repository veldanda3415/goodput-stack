"""T4 engine track: runs INSIDE a Kaggle kernel, one stage per push (benchmarks/kaggle/run_kaggle.py).

    python -m benchmarks.kaggle.t4_notebook --stage smoke
    python -m benchmarks.kaggle.t4_notebook --stage baseline --vllm-versions 0.31.0,0.30.0

Every stage writes /kaggle/working/results/<stage>/ (override: GOODPUT_RESULTS):
    <stage>.jsonl   result rows; each carries provenance (time, git sha, GPU/driver/CUDA, vLLM version,
                    model + revision, serving flags, client config) and a `key`. A key already in the
                    file is skipped, so re-pushing a stage with --resume continues where it stopped.
    env.json        nvidia-smi / python / package versions for this session
    logs/           raw server logs, /metrics scrapes, tool output
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(os.environ.get("GOODPUT_RESULTS", "/kaggle/working/results"))
GIT_SHA = os.environ.get("GOODPUT_GIT_SHA", "unknown")
RUN_ID = os.environ.get("GOODPUT_RUN_ID", "local")
PORT = 8000
STAGE_ARGS: dict = {}   # stage -> [add_argument callbacks]
HF_REPOS_TO_CHECK = ["meta-llama/Llama-3.2-3B-Instruct", "meta-llama/Llama-3.1-8B-Instruct",
                     "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4", "Qwen/Qwen2.5-3B-Instruct",
                     "Qwen/Qwen2.5-3B-Instruct-AWQ", "Qwen/Qwen2.5-3B-Instruct-GGUF"]


# ---------------------------------------------------------------- plumbing

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def sh(cmd: str | list[str], timeout: float = 600, out: Path | None = None, env: dict | None = None) -> tuple[int, str]:
    """Run a command; return (rc, combined output). rc 124 = timeout. Output also saved to `out`."""
    args = cmd if isinstance(cmd, list) else ["bash", "-lc", cmd]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        rc, text = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as exc:
        rc, text = 124, f"TIMEOUT after {timeout}s\n{exc.stdout or ''}{exc.stderr or ''}"
    except OSError as exc:
        rc, text = 127, str(exc)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"$ {cmd if isinstance(cmd, str) else shlex.join(cmd)}\n# rc={rc}\n{text}")
    return rc, text


class Stage:
    def __init__(self, name: str):
        self.name = name
        self.dir = RESULTS / name
        self.logs = self.dir / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.dir / f"{name}.jsonl"
        self.env = env_info(self.dir / "env.json")
        self.t0 = time.time()

    def done(self) -> set[str]:
        if not self.jsonl.exists():
            return set()
        return {json.loads(l).get("key") for l in self.jsonl.read_text().splitlines() if l.strip()}

    def rows(self) -> list[dict]:
        if not self.jsonl.exists():
            return []
        return [json.loads(l) for l in self.jsonl.read_text().splitlines() if l.strip()]

    def write(self, key: str, row: dict, **prov) -> dict:
        full = {"key": key, "stage": self.name, "timestamp_utc": now(), "git_sha": GIT_SHA, "run_id": RUN_ID,
                "gpu": self.env.get("gpu_name"), "driver": self.env.get("driver_version"),
                "cuda_driver": self.env.get("cuda_version_driver"), **prov, **row}
        with open(self.jsonl, "a") as f:
            f.write(json.dumps(full, default=str) + "\n")
        log(f"row {key}: " + json.dumps({k: v for k, v in row.items() if not isinstance(v, (dict, list))}, default=str)[:400])
        return full


def env_info(path: Path) -> dict:
    info: dict = {"timestamp_utc": now(), "python": sys.version.split()[0]}
    rc, q = sh(["nvidia-smi", "--query-gpu=index,name,driver_version,memory.total,pci.bus_id", "--format=csv,noheader"])
    if rc == 0:
        gpus = [[x.strip() for x in l.split(",")] for l in q.strip().splitlines()]
        info |= {"gpu_count": len(gpus), "gpus": gpus, "gpu_name": gpus[0][1], "driver_version": gpus[0][2],
                 "gpu_memory_total": gpus[0][3]}
    rc, full = sh(["nvidia-smi"])
    m = re.search(r"CUDA Version:\s*([\d.]+)", full)
    info["cuda_version_driver"] = m.group(1) if m else None   # max CUDA the driver supports (nvidia-smi header)
    for pkg in ("torch", "vllm", "transformers", "nvidia-ml-py", "pynvml", "huggingface_hub"):
        rc, o = sh([sys.executable, "-m", "pip", "show", pkg], timeout=60)
        m = re.search(r"^Version:\s*(\S+)", o, re.M)
        info[f"pkg_{pkg}"] = m.group(1) if rc == 0 and m else None
    path.write_text(json.dumps(info, indent=2) + "\n")
    return info


def hf_token() -> str | None:
    """HF token from env or a Kaggle secret named HF_TOKEN; never printed or stored."""
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    global HF_SECRET_ERROR
    try:
        from kaggle_secrets import UserSecretsClient
        tok = UserSecretsClient().get_secret("HF_TOKEN")
        if tok:
            os.environ["HF_TOKEN"] = tok
        return tok
    except Exception as exc:
        HF_SECRET_ERROR = f"{type(exc).__name__}: {str(exc)[:200]}"
        return None


HF_SECRET_ERROR = None


def hf_access(repo: str) -> dict:
    """model_info() (metadata) AND a config.json download. Smoke run 1 showed model_info succeeds on a
    gated repo without any token, so only the file download says whether weights can be fetched."""
    from huggingface_hub import hf_hub_download, model_info
    out: dict = {"repo": repo}
    try:
        mi = model_info(repo, token=hf_token())
        out |= {"model_info": "ok", "sha": mi.sha, "gated": getattr(mi, "gated", None)}
    except Exception as exc:
        out |= {"model_info": "error", "model_info_error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    try:
        hf_hub_download(repo, "config.json" if "GGUF" not in repo else "README.md", token=hf_token())
        out["download"] = "ok"
    except Exception as exc:
        out |= {"download": "denied", "download_error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    out["access"] = "ok" if out.get("download") == "ok" else "denied"
    return out


# ---------------------------------------------------------------- vLLM install + server

def pip_install_vllm(version: str, logs: Path) -> dict:
    t0 = time.time()
    # Kaggle preinstalls torchaudio/torchcodec/torchvision built for its torch (cu128). vLLM brings its own
    # torch (cu130 in baseline run 1), and `import vllm` then dies on the CUDA mismatch with torchaudio.
    # Remove them first; vLLM reinstalls the torchvision it pins.
    sh([sys.executable, "-m", "pip", "uninstall", "-y", "torchaudio", "torchcodec", "torchvision"], timeout=300,
       out=logs / f"pip-uninstall-before-vllm-{version}.txt")
    rc, out = sh([sys.executable, "-m", "pip", "install", "-q", f"vllm=={version}"], timeout=1500,
                 out=logs / f"pip-install-vllm-{version}.txt")
    rc2, ver = sh(["vllm", "--version"], timeout=180)
    rc3, torch_v = sh([sys.executable, "-c", "import torch;print(torch.__version__, torch.version.cuda)"], timeout=120)
    return {"vllm_version_requested": version, "pip_rc": rc, "pip_s": round(time.time() - t0, 1), "vllm_import_rc": rc2,
            "pip_tail": out.strip()[-800:] if rc else "", "vllm_version_reported": ver.strip().splitlines()[-1] if rc2 == 0 else ver[-300:],
            "torch_after_install": torch_v.strip() if rc3 == 0 else torch_v[-300:]}


def serve_help(logs: Path, version: str) -> str:
    """`vllm serve --help=all` (all groups); falls back to plain --help. Saved so flag names are checkable."""
    rc, text = sh(["vllm", "serve", "--help=all"], timeout=300, out=logs / f"vllm-serve-help-{version}.txt")
    if rc != 0 or "--gpu-memory-utilization" not in text:
        rc, text = sh(["vllm", "serve", "--help"], timeout=300, out=logs / f"vllm-serve-help-{version}.txt")
    return text


def require_flags(help_text: str, flags: list[str]) -> list[str]:
    """Flags (e.g. --max-num-seqs) missing from the help text; never pass a flag the version doesn't list."""
    return [f for f in flags if not re.search(re.escape(f) + r"(?![\w-])", help_text)]


class VllmServer:
    """`vllm serve` subprocess on GPU 0 with its log in a file; start() waits for /health or exit."""

    def __init__(self, model: str, flags: list[str], log_path: Path, served_name: str | None = None):
        self.model, self.flags, self.log_path = model, flags, log_path
        self.served_name = served_name or model
        self.cmd = ["vllm", "serve", model, "--port", str(PORT), "--served-model-name", self.served_name, *flags]
        self.proc: subprocess.Popen | None = None
        self.base_url = f"http://127.0.0.1:{PORT}"

    def start(self, timeout_s: float = 1500) -> dict:
        import httpx
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.log_path, "a")   # a restart appends to the same log
        self._f.write("$ " + shlex.join(self.cmd) + "\n")
        self._f.flush()
        env = dict(os.environ, CUDA_VISIBLE_DEVICES="0")
        t0 = time.time()
        self.proc = subprocess.Popen(self.cmd, stdout=self._f, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        while time.time() - t0 < timeout_s:
            if self.proc.poll() is not None:
                return {"started": False, "exit_code": self.proc.returncode, "startup_s": round(time.time() - t0, 1)}
            try:
                if httpx.get(self.base_url + "/health", timeout=2).status_code == 200:
                    return {"started": True, "startup_s": round(time.time() - t0, 1)}
            except httpx.HTTPError:
                pass
            time.sleep(2)
        return {"started": False, "exit_code": "timeout", "startup_s": round(time.time() - t0, 1)}

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGINT)
            try:
                self.proc.wait(60)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(30)
        if getattr(self, "_f", None):
            self._f.close()
        time.sleep(3)   # let the GPU memory be released before the next start

    def log_text(self) -> str:
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""

    def __enter__(self) -> "VllmServer":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


STARTUP_PATTERNS = {
    "gpu_kv_cache_tokens": r"GPU KV cache size:\s*([\d,]+)\s*tokens",
    "max_concurrency_log": r"Maximum concurrency for\s*([\d,]+)\s*tokens per request:\s*([\d.]+)x",
    "num_gpu_blocks_log": r"#\s*GPU blocks:\s*(\d+)",
    "model_weights_gib": r"Model loading took\s*([\d.]+)\s*Gi?B",
    "available_kv_gib": r"Available KV cache memory:\s*([\d.]+)\s*GiB",
    "block_size_config": r"block_size[=:]\s*(\d+)",
}
STARTUP_KEYWORDS = ("backend", "KV cache", "GPU blocks", "Model loading took", "Maximum concurrency", "memory",
                    "CUDA graph", "dtype", "Error", "error", "compute capability", "not supported", "sm_75", "Turing")


def parse_startup(log_text: str) -> dict:
    out: dict = {}
    for key, pat in STARTUP_PATTERNS.items():
        m = re.search(pat, log_text)
        if not m:
            continue
        if key == "max_concurrency_log":
            out["max_concurrency_len_log"] = int(m.group(1).replace(",", ""))
            out[key] = float(m.group(2))
        elif key in ("model_weights_gib", "available_kv_gib"):
            out[key] = float(m.group(1))
        else:
            out[key] = int(m.group(1).replace(",", ""))
    out["attention_backend_lines"] = [l.strip()[-220:] for l in log_text.splitlines()
                                      if re.search(r"attention backend|_ATTN|FLASH|TRITON|FLEX|XFORMERS", l)][:8]
    out["startup_lines"] = [l.strip()[-260:] for l in log_text.splitlines()
                            if any(k in l for k in STARTUP_KEYWORDS)][:60]
    return out


def error_lines(log_text: str, n: int = 25) -> list[str]:
    lines = log_text.splitlines()
    errs = [l.strip()[-300:] for l in lines if re.search(r"Error|error|ERROR|Traceback|not supported|RuntimeError", l)]
    return (errs[-n:] or [l[-300:] for l in lines[-n:]])


def metrics_text(base_url: str) -> str:
    import httpx
    return httpx.get(base_url + "/metrics", timeout=10).text


def cache_config_info(text: str) -> dict:
    """Labels of vllm:cache_config_info (block_size, num_gpu_blocks, ...) from a raw /metrics scrape."""
    m = re.search(r"^vllm:cache_config_info\{([^}]*)\}", text, re.M)
    return dict(re.findall(r'(\w+)="([^"]*)"', m.group(1))) if m else {}


METRIC_ROLES = {   # role -> substrings matched against the metric names the server actually exports
    "ttft": ["time_to_first_token"], "itl": ["inter_token_latency", "time_per_output_token"],
    "waiting": ["num_requests_waiting"], "running": ["num_requests_running"],
    "kv_usage": ["kv_cache_usage", "gpu_cache_usage"], "preemptions": ["preemption"],
    "queue_time": ["request_queue_time"], "prefix_cache": ["prefix_cache"],
}


def metric_names(text: str) -> dict:
    names = sorted(set(re.findall(r"^# TYPE (\S+) (\w+)", text, re.M)))
    roles = {role: [f"{n} ({t})" for n, t in names if any(s in n for s in subs)] for role, subs in METRIC_ROLES.items()}
    return {"all": [f"{n} ({t})" for n, t in names], "roles": roles}


def model_revision(repo: str) -> str | None:
    try:
        from huggingface_hub import model_info
        return model_info(repo, token=hf_token()).sha
    except Exception:
        return None


def save_config_json(repo: str, dest: Path) -> dict | None:
    try:
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(repo, "config.json", token=hf_token())
        dest.write_text(Path(p).read_text())
        return json.loads(dest.read_text())
    except Exception as exc:
        dest.with_suffix(".error.txt").write_text(str(exc))
        return None


def choose_model(preferred: str, fallback: str, st: Stage) -> tuple[str, dict]:
    acc = hf_access(preferred)
    if acc["access"] == "ok":
        return preferred, {"model_choice": "preferred", "access_check": acc}
    return fallback, {"model_choice": f"SUBSTITUTE for {preferred} (no download access)", "access_check": acc}


# ---------------------------------------------------------------- requests

def chat(base_url: str, model: str, prompt: str, max_tokens: int, stream: bool, ignore_eos: bool = False) -> dict:
    """One /v1/chat/completions call. TTFT = first chunk with non-empty delta.content (scripts/README.md)."""
    import httpx
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0.0, "stream": stream, "ignore_eos": ignore_eos}
    if stream:
        body["stream_options"] = {"include_usage": True}
    t0 = time.perf_counter()
    rec: dict = {"stream": stream, "max_tokens": max_tokens}
    with httpx.Client(timeout=600) as c:
        if not stream:
            r = c.post(base_url + "/v1/chat/completions", json=body)
            rec |= {"status": r.status_code, "e2e_s": round(time.perf_counter() - t0, 4)}
            if r.status_code == 200:
                j = r.json()
                rec |= {"usage": j.get("usage"), "finish_reason": j["choices"][0].get("finish_reason"),
                        "content_head": (j["choices"][0]["message"].get("content") or "")[:120]}
            else:
                rec["error"] = r.text[:400]
            return rec
        times, usage, text = [], None, []
        with c.stream("POST", base_url + "/v1/chat/completions", json=body) as r:
            rec["status"] = r.status_code
            if r.status_code != 200:
                rec["error"] = r.read().decode(errors="replace")[:400]
                return rec
            for line in r.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                j = json.loads(line[6:])
                if j.get("usage"):
                    usage = j["usage"]
                for ch in j.get("choices") or []:
                    piece = (ch.get("delta") or {}).get("content")
                    if piece:
                        times.append(time.perf_counter())
                        text.append(piece)
    t_end = time.perf_counter()
    rec |= {"e2e_s": round(t_end - t0, 4), "content_chunks": len(times), "usage": usage,
            "content_head": "".join(text)[:120]}
    if times:
        rec["ttft_s"] = round(times[0] - t0, 4)
    if len(times) > 1:
        # decode rate after the first token, from the stream; completion_tokens from usage when present
        n = (usage or {}).get("completion_tokens") or len(times)
        rec["decode_tok_s_chunks"] = round((len(times) - 1) / (times[-1] - times[0]), 3)
        rec["decode_tok_s_usage"] = round((n - 1) / (times[-1] - times[0]), 3)
        rec["e2e_tok_s_usage"] = round(n / (t_end - t0), 3)
    return rec


DECODE_PROMPT = "Write a long, detailed essay about the history of computing, from mechanical calculators to GPUs."


def throttle_counters() -> dict:
    """Clock-event (throttle) reason counters in us from `nvidia-smi -q -d PERFORMANCE`, GPU 0."""
    rc, out = sh(["nvidia-smi", "-i", "0", "-q", "-d", "PERFORMANCE"], timeout=60)
    sec = out.split("Clocks Event Reasons Counters")[-1] if "Counters" in out else ""
    return {k.strip(): int(v) for k, v in re.findall(r"^\s*([A-Za-z ]+?)\s*:\s*(\d+) us", sec, re.M)}


def batch1_decode(base_url: str, model: str, runs: int, max_tokens: int, gpu_dir: Path | None = None) -> dict:
    """`runs` sequential streamed chat requests, same prompt, ignore_eos, temperature 0 -> median and spread.
    With gpu_dir: NVML 1 Hz CSV per run + throttle-reason counter deltas (baseline run 2 spread was 64 %)."""
    import statistics
    from benchmarks.gpu_sampler import GpuSampler, summarize as gpu_summary
    chat(base_url, model, DECODE_PROMPT, 16, stream=True)   # warmup, discarded
    recs = []
    for i in range(runs):
        if gpu_dir is None:
            recs.append(chat(base_url, model, DECODE_PROMPT, max_tokens, stream=True, ignore_eos=True))
            continue
        gpu_dir.mkdir(parents=True, exist_ok=True)
        before = throttle_counters()
        with GpuSampler(gpu_dir / f"decode-run{i}.csv", 1.0, 0):
            r = chat(base_url, model, DECODE_PROMPT, max_tokens, stream=True, ignore_eos=True)
        after = throttle_counters()
        r |= gpu_summary(gpu_dir / f"decode-run{i}.csv")
        r["throttle_us_delta"] = {k: after[k] - before.get(k, 0) for k in after}
        recs.append(r)
    vals = [r["decode_tok_s_usage"] for r in recs if r.get("decode_tok_s_usage")]
    out = {"decode_runs": recs, "decode_prompt": DECODE_PROMPT, "decode_max_tokens": max_tokens, "decode_n": len(vals)}
    if vals:
        med = statistics.median(vals)
        out |= {"decode_tok_s_median": round(med, 2), "decode_tok_s_min": min(vals), "decode_tok_s_max": max(vals),
                "decode_spread_pct": round((max(vals) - min(vals)) / med * 100, 2),
                "ttft_s_median": statistics.median([r["ttft_s"] for r in recs if "ttft_s" in r])}
    return out


# ---------------------------------------------------------------- harness load (benchmarks/harness/client.py)

def client_cfg(model: str, concurrency: int, requests: int, prompt_tokens: int = 256, max_tokens: int = 128,
               arrival_rate: float | None = None, warmup: int = 2) -> dict:
    return {"api": "openai", "model": model, "endpoint": "/v1/completions", "prompt_tokens": prompt_tokens,
            "max_tokens": max_tokens, "max_tokens_jitter": 0.25, "ignore_eos": True, "temperature": 0.0,
            "concurrency": concurrency, "requests": requests, "requests_per_client": None, "min_requests": 0,
            "start_jitter_s": 1.0 if concurrency > 1 else 0, "warmup": warmup, "timeout_s": 900,
            "cache_prompt": False, "arrival_rate": arrival_rate, "arrival_seed": 7}


def vllm_metric_summary(samples: list[dict]) -> dict:
    """running / waiting / KV usage / preemptions from the 1 s /metrics samples (names discovered, not assumed)."""
    ms = [s["metrics"] for s in samples if "metrics" in s]
    if not ms:
        return {}
    def pick(subs):
        return next((n for n in ms[-1] if any(s in n for s in subs) and not n.endswith(("_created",))), None)
    out: dict = {}
    for role, subs in (("running", ["num_requests_running"]), ("waiting", ["num_requests_waiting"]),
                       ("kv_usage", ["kv_cache_usage_perc", "gpu_cache_usage_perc"])):
        n = pick(subs)
        if n:
            vals = [m.get(n, 0) for m in ms]
            out |= {f"srv_{role}_max": max(vals), f"srv_{role}_mean": round(sum(vals) / len(vals), 4), f"srv_{role}_metric": n}
    n = pick(["num_preemptions_total", "num_preemptions"])
    if n:
        out |= {"srv_preemptions": ms[-1].get(n, 0) - ms[0].get(n, 0), "srv_preemptions_metric": n}
    return out


def harness_point(base_url: str, cfg_client: dict, point_dir: Path, gpu_csv: Path) -> dict:
    import asyncio
    from benchmarks.gpu_sampler import GpuSampler, summarize as gpu_summary
    from benchmarks.harness import client, stats, storage
    cfg = {"client": cfg_client, "metrics": {"scrape_interval_s": 1.0}}
    point_dir.mkdir(parents=True, exist_ok=True)
    with GpuSampler(gpu_csv, 1.0, 0):
        result = asyncio.run(client.run_point(base_url, cfg))
    storage.write_jsonl(point_dir / "requests.jsonl", result["records"])
    storage.write_jsonl(point_dir / "metrics.jsonl", result["samples"])
    row = stats.summarize_load(result)
    row["req_s"] = round(row["requests_ok"] / result["wall_s"], 3) if result["wall_s"] else None
    errors = [r.get("error") or f"status {r.get('status')}" for r in result["records"] if not r.get("ok")]
    row["errors"] = len(errors)
    row["error_examples"] = errors[:3]
    return row | vllm_metric_summary(result["samples"]) | gpu_summary(gpu_csv)


# ---------------------------------------------------------------- stages

def stage_smoke(a) -> None:
    st = Stage("smoke")
    sh(["nvidia-smi"], out=st.logs / "nvidia-smi.txt")
    sh(["nvidia-smi", "-q"], out=st.logs / "nvidia-smi-q.txt")
    rc_v, vllm_show = sh([sys.executable, "-m", "pip", "show", "vllm"], out=st.logs / "pip-show-vllm.txt")
    sh([sys.executable, "-m", "pip", "list"], out=st.logs / "pip-list.txt")
    rc_d, dcgm = sh("command -v dcgmi && dcgmi discovery -l; command -v nv-hostengine; ls /usr/lib/x86_64-linux-gnu | grep -i dcgm",
                    out=st.logs / "dcgm.txt", timeout=60)
    try:
        import pynvml  # noqa: F401
        nvml = "importable"
    except ImportError as exc:
        nvml = f"not importable: {exc}"
    sh("df -h /kaggle/working /tmp /root; free -g; nproc; cat /etc/os-release | head -3", out=st.logs / "host.txt")
    access = [hf_access(r) for r in HF_REPOS_TO_CHECK]
    st.write("smoke", {"pip_show_vllm_rc": rc_v, "pip_show_vllm": vllm_show.strip()[:300], "pynvml": nvml,
                       "dcgm_probe_rc": rc_d, "dcgm_probe": dcgm.strip()[:500], "hf_token_present": hf_token() is not None, "hf_secret_error": HF_SECRET_ERROR,
                       "hf_access": access, "env": st.env})


BASE_FLAGS = ["--dtype", "--gpu-memory-utilization", "--max-model-len", "--max-num-seqs",
              "--no-enable-prefix-caching", "--served-model-name", "--port"]


def install_working_vllm(st: Stage, versions: list[str], model: str, flags: list[str]) -> tuple[str | None, VllmServer | None, dict]:
    """Try versions in order: install, check flags, start. Every attempt is a row (key attempt-<v>).
    Returns the first version that serves, with its server still running."""
    for v in versions:
        inst = pip_install_vllm(v, st.logs)
        row = {"kind": "vllm_attempt"} | inst
        if inst["pip_rc"] != 0:
            st.write(f"attempt-{v}", row | {"result": "pip install failed"})
            continue
        if inst["vllm_import_rc"] != 0:
            st.write(f"attempt-{v}", row | {"result": "`vllm --version` failed (import error)"})
            continue
        missing = require_flags(serve_help(st.logs, v), BASE_FLAGS)
        if missing:
            st.write(f"attempt-{v}", row | {"result": f"flags missing from serve --help: {missing}"})
            continue
        srv = VllmServer(model, flags, st.logs / f"server-attempt-{v}.log")
        res = srv.start()
        text = srv.log_text()
        row |= res | {"serve_cmd": shlex.join(srv.cmd)}
        if res["started"]:
            st.write(f"attempt-{v}", row | {"result": "serves"} | {k: v_ for k, v_ in parse_startup(text).items()
                                                                     if k != "startup_lines"})
            return v, srv, inst
        srv.stop()
        st.write(f"attempt-{v}", row | {"result": "server failed to start", "error_lines": error_lines(text)})
    return None, None, {}


def stage_baseline(a) -> None:
    """Task 1: find a vLLM that serves on the T4, startup facts, chat API checks, batch-1 decode, /metrics."""
    st = Stage("baseline")
    model, choice = choose_model(a.model, a.fallback_model, st)
    rev = model_revision(model)
    cfgjson = save_config_json(model, st.logs / "model-config.json")
    flags = ["--dtype", "half", "--gpu-memory-utilization", str(a.gpu_mem), "--max-model-len", str(a.max_model_len),
             "--no-enable-prefix-caching"]
    prov = {"model": model, "model_revision": rev, "serving_flags": flags} | choice
    version, srv, inst = install_working_vllm(st, a.vllm_versions.split(","), model, flags)
    if not srv:
        st.write("baseline-failed", {"result": "no vLLM version in the list served on this GPU"}, **prov)
        return
    prov |= {"vllm_version": version, "torch": inst.get("torch_after_install")}
    try:
        text = srv.log_text()
        idle = metrics_text(srv.base_url)
        (st.logs / "metrics-idle.txt").write_text(idle)
        startup = parse_startup(text)
        cci = cache_config_info(idle)
        kv = {"num_gpu_blocks": int(cci["num_gpu_blocks"]) if cci.get("num_gpu_blocks", "").isdigit() else startup.get("num_gpu_blocks_log"),
              "block_size": int(cci["block_size"]) if cci.get("block_size", "").isdigit() else startup.get("block_size_config")}
        if kv["num_gpu_blocks"] and kv["block_size"]:
            kv["blocks_x_block_size"] = kv["num_gpu_blocks"] * kv["block_size"]
        st.write("startup", {"kind": "startup", **startup, **kv, "cache_config_info": cci,
                             "model_config_json": {k: (cfgjson or {}).get(k) for k in
                                                   ("num_hidden_layers", "num_attention_heads", "num_key_value_heads",
                                                    "hidden_size", "head_dim", "torch_dtype", "max_position_embeddings")}},
                 **prov)
        names = metric_names(idle)
        (st.logs / "metric-names.json").write_text(json.dumps(names, indent=2))
        st.write("metric-names", {"kind": "metric_names", "source": "/metrics # TYPE lines, idle scrape",
                                  "roles": names["roles"]}, **prov)
        for stream in (False, True):
            r = chat(srv.base_url, model, "Say hello in five words.", 32, stream=stream)
            st.write(f"chat-{'stream' if stream else 'nonstream'}", {"kind": "api_check", **r}, **prov)
        dec = batch1_decode(srv.base_url, model, a.decode_runs, a.decode_max_tokens, st.dir / "decode-gpu")
        st.write("decode-batch1", {"kind": "decode_batch1", **dec}, **prov,
                 client={"endpoint": "/v1/chat/completions", "stream": True, "temperature": 0, "ignore_eos": True,
                         "max_tokens": a.decode_max_tokens, "runs": a.decode_runs, "warmup": 1})
        # /metrics under load: a c=16 harness point in a thread, one raw scrape in the middle of it
        import threading
        cc = client_cfg(model, 16, 48)
        box: dict = {}
        t = threading.Thread(target=lambda: box.update(row=harness_point(srv.base_url, cc, st.dir / "load-c16",
                                                                            st.dir / "load-c16" / "gpu.csv")))
        t.start()
        time.sleep(25)
        (st.logs / "metrics-load.txt").write_text(metrics_text(srv.base_url))
        t.join()
        st.write("load-c16", {"kind": "load_point", **box.get("row", {})}, **prov, client=cc)
        (st.logs / "metrics-after.txt").write_text(metrics_text(srv.base_url))
    finally:
        srv.stop()
        (st.logs / "server.log").write_text(srv.log_text())


STAGE_ARGS["baseline"] = [
    lambda p: p.add_argument("--model", default="meta-llama/Llama-3.2-3B-Instruct"),
    lambda p: p.add_argument("--fallback-model", default="Qwen/Qwen2.5-3B-Instruct"),
    lambda p: p.add_argument("--vllm-versions", default="0.31.0,0.30.0,0.29.0,0.28.0"),
    lambda p: p.add_argument("--gpu-mem", type=float, default=0.90),
    lambda p: p.add_argument("--max-model-len", type=int, default=4096),
    lambda p: p.add_argument("--decode-runs", type=int, default=5),
    lambda p: p.add_argument("--decode-max-tokens", type=int, default=256),
]

def install_pinned(st: Stage, version: str) -> dict:
    inst = pip_install_vllm(version, st.logs)
    if inst["pip_rc"] != 0 or inst["vllm_import_rc"] != 0:
        raise RuntimeError(f"vllm=={version} not usable: {inst['pip_tail'] or inst['vllm_version_reported']}")
    return inst


def stage_kvgrid(a) -> None:
    """Task 2: 8B AWQ INT4 - started?, GPU blocks, KV tokens, max concurrent full-length sequences per cell."""
    st = Stage("kvgrid")
    inst = install_pinned(st, a.vllm_version)
    help_text = serve_help(st.logs, a.vllm_version)
    model, rev = a.model, model_revision(a.model)
    save_config_json(model, st.logs / "model-config.json")
    done = st.done()
    for util in [float(x) for x in a.utils.split(",")]:
        for mlen in [int(x) for x in a.lens.split(",")]:
            key = f"kv-{util}-{mlen}"
            if key in done:
                log(f"skip {key} (done)")
                continue
            flags = ["--dtype", "half", "--gpu-memory-utilization", str(util), "--max-model-len", str(mlen),
                     "--no-enable-prefix-caching"]
            missing = require_flags(help_text, ["--dtype", "--gpu-memory-utilization", "--max-model-len"])
            prov = {"model": model, "model_revision": rev, "serving_flags": flags, "vllm_version": a.vllm_version,
                    "torch": inst["torch_after_install"]}
            srv = VllmServer(model, flags, st.logs / f"server-{key}.log")
            with srv:
                res = srv.start(timeout_s=1500)
                row: dict = {"kind": "kv_cell", "gpu_memory_utilization": util, "max_model_len": mlen,
                             "flags_missing": missing, **res}
                text = srv.log_text()
                startup = parse_startup(text)
                row |= {k: v for k, v in startup.items() if k != "startup_lines"}
                if res["started"]:
                    cci = cache_config_info(metrics_text(srv.base_url))
                    row["cache_config_info"] = cci
                    blocks = int(cci["num_gpu_blocks"]) if cci.get("num_gpu_blocks", "").isdigit() else startup.get("num_gpu_blocks_log")
                    bsz = int(cci["block_size"]) if cci.get("block_size", "").isdigit() else startup.get("block_size_config")
                    row |= {"num_gpu_blocks": blocks, "block_size": bsz}
                    kv_tokens = startup.get("gpu_kv_cache_tokens") or (blocks * bsz if blocks and bsz else None)
                    row["kv_tokens"] = kv_tokens
                    if "max_concurrency_log" in startup:
                        row |= {"max_full_len_seqs": startup["max_concurrency_log"], "max_full_len_seqs_source": "vLLM startup log"}
                    elif kv_tokens:
                        row |= {"max_full_len_seqs": round(kv_tokens / mlen, 2), "max_full_len_seqs_source": "computed kv_tokens / max_model_len"}
                    r = chat(srv.base_url, model, "Say hello in five words.", 16, stream=False)
                    row["chat_check_status"] = r.get("status")
                else:
                    row["error_lines"] = error_lines(text)
                st.write(key, row, **prov)


STAGE_ARGS["kvgrid"] = [
    lambda p: p.add_argument("--vllm-version", required=True),
    lambda p: p.add_argument("--model", default="hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"),
    lambda p: p.add_argument("--utils", default="0.80,0.90,0.95"),
    lambda p: p.add_argument("--lens", default="2048,4096,8192,16384"),
]


def help_default(help_text: str, flag: str) -> str | None:
    """The 'Default: X' printed under a flag in `vllm serve --help=all`."""
    m = re.search(re.escape(flag) + r"(?![\w-]).*?Default:\s*([^\s)]+)", help_text, re.S)
    return m.group(1).rstrip(".") if m else None


def bench_serve(st: Stage, model: str, concurrency: int, num_prompts: int, input_len: int, output_len: int) -> dict:
    """Cross-check with the benchmark tool shipped in the pinned vLLM (`vllm bench serve`)."""
    rc, help_text = sh(["vllm", "bench", "serve", "--help"], timeout=300, out=st.logs / "vllm-bench-serve-help.txt")
    want = ["--backend", "--base-url", "--model", "--endpoint", "--dataset-name", "--random-input-len",
            "--random-output-len", "--num-prompts", "--max-concurrency", "--ignore-eos", "--save-result",
            "--result-dir", "--result-filename", "--percentile-metrics", "--metric-percentiles"]
    missing = require_flags(help_text, want)
    if rc != 0 or missing:
        return {"bench_rc": rc, "bench_flags_missing": missing}
    out_dir = st.dir / "bench_serve"
    out_dir.mkdir(exist_ok=True)
    fname = f"bench-c{concurrency}.json"
    cmd = ["vllm", "bench", "serve", "--backend", "vllm", "--base-url", f"http://127.0.0.1:{PORT}", "--model", model,
           "--endpoint", "/v1/completions", "--dataset-name", "random", "--random-input-len", str(input_len),
           "--random-output-len", str(output_len), "--num-prompts", str(num_prompts), "--max-concurrency", str(concurrency),
           "--ignore-eos", "--percentile-metrics", "ttft,tpot,itl,e2el", "--metric-percentiles", "50,95,99",
           "--save-result", "--result-dir", str(out_dir), "--result-filename", fname]
    rc, out = sh(cmd, timeout=1800, out=st.logs / f"vllm-bench-serve-c{concurrency}.txt")
    row = {"bench_cmd": shlex.join(cmd), "bench_rc": rc}
    if (out_dir / fname).exists():
        j = json.loads((out_dir / fname).read_text())
        row["bench"] = {k: v for k, v in j.items() if not isinstance(v, list)}
    else:
        row["bench_tail"] = out[-1500:]
    return row


def stage_sweep(a) -> None:
    """Task 4: closed loop c=1..64 at two --max-num-seqs, open loop at 3 rates around the knee, bench cross-check."""
    st = Stage("sweep")
    inst = install_pinned(st, a.vllm_version)
    help_text = serve_help(st.logs, a.vllm_version)
    model, choice = choose_model(a.model, a.fallback_model, st)
    rev = model_revision(model)
    default_mns = help_default(help_text, "--max-num-seqs")
    st.write("max-num-seqs-default", {"kind": "note", "max_num_seqs_default_from_help": default_mns,
                                      "source": "vllm serve --help=all"}, vllm_version=a.vllm_version)
    concs = [int(x) for x in a.concurrency.split(",")]
    done = st.done()
    for mns in a.max_num_seqs.split(","):
        flags = ["--dtype", "half", "--gpu-memory-utilization", "0.9", "--max-model-len", "4096", "--no-enable-prefix-caching"]
        if mns != "default":
            flags += ["--max-num-seqs", mns]
        prov = {"model": model, "model_revision": rev, "serving_flags": flags, "vllm_version": a.vllm_version,
                "torch": inst["torch_after_install"], "max_num_seqs": mns if mns != "default" else f"default ({default_mns})",
                "prefix_caching": "disabled (--no-enable-prefix-caching) + unique random prompts"} | choice
        todo = [c for c in concs if f"closed-mns{mns}-c{c}" not in done]
        open_needed = mns == "default" and a.open_loop
        bench_needed = mns == "default" and a.bench and any(f"bench-c{c}" not in done for c in (1, 16))
        if not todo and not open_needed and not bench_needed:
            continue
        srv = VllmServer(model, flags, st.logs / f"server-mns{mns}.log")
        with srv:
            res = srv.start()
            if not res["started"]:
                st.write(f"server-mns{mns}", {"kind": "server_fail", **res, "error_lines": error_lines(srv.log_text())}, **prov)
                continue
            for c in todo:
                cc = client_cfg(model, c, max(20, 4 * c))
                row = harness_point(srv.base_url, cc, st.dir / f"mns{mns}-c{c}", st.dir / f"mns{mns}-c{c}" / "gpu.csv")
                st.write(f"closed-mns{mns}-c{c}", {"kind": "closed_loop", "concurrency": c, **row}, **prov, client=cc)
            if open_needed:
                closed = [r for r in st.rows() if r["key"].startswith(f"closed-mns{mns}-c") and r.get("steady_output_tok_s")]
                if closed:
                    best = max(r["steady_output_tok_s"] for r in closed)
                    knee = min((r for r in closed if r["steady_output_tok_s"] >= 0.9 * best), key=lambda r: r["concurrency"])
                    knee_rps = knee["req_s"]
                    st.write("knee", {"kind": "knee", "rule": "smallest concurrency with steady_output_tok_s >= 90% of max",
                                      "knee_concurrency": knee["concurrency"], "knee_req_s": knee_rps,
                                      "max_steady_output_tok_s": best, "rates": [round(knee_rps * f, 3) for f in (0.75, 1.0, 1.25)]}, **prov)
                    for f in (0.75, 1.0, 1.25):
                        rate = round(knee_rps * f, 3)
                        key = f"open-x{f}"
                        if key in done:
                            continue
                        cc = client_cfg(model, 512, max(40, int(rate * 90)), arrival_rate=rate)
                        row = harness_point(srv.base_url, cc, st.dir / key, st.dir / key / "gpu.csv")
                        st.write(key, {"kind": "open_loop", "arrival_rate": rate, "knee_factor": f, **row}, **prov, client=cc)
            if bench_needed:
                for c in (1, 16):
                    if f"bench-c{c}" in done:
                        continue
                    from benchmarks.gpu_sampler import GpuSampler
                    with GpuSampler(st.dir / f"bench-c{c}-gpu.csv"):
                        row = bench_serve(st, model, c, max(20, 4 * c), 256, 128)
                    st.write(f"bench-c{c}", {"kind": "bench_serve", "concurrency": c, **row}, **prov)
            (st.logs / f"metrics-end-mns{mns}.txt").write_text(metrics_text(srv.base_url))


STAGE_ARGS["sweep"] = [
    lambda p: p.add_argument("--vllm-version", required=True),
    lambda p: p.add_argument("--model", default="meta-llama/Llama-3.2-3B-Instruct"),
    lambda p: p.add_argument("--fallback-model", default="Qwen/Qwen2.5-3B-Instruct"),
    lambda p: p.add_argument("--concurrency", default="1,2,4,8,16,32,64"),
    lambda p: p.add_argument("--max-num-seqs", default="default,8"),
    lambda p: p.add_argument("--no-open-loop", dest="open_loop", action="store_false"),
    lambda p: p.add_argument("--no-bench", dest="bench", action="store_false"),
]


# ---------------------------------------------------------------- Task 5: quantization

class LlamaCppServer(VllmServer):
    """llama-server (llama.cpp CUDA build) with the same start/stop/log contract as VllmServer."""

    def __init__(self, binary: str, gguf: str, flags: list[str], log_path: Path, served_name: str):
        super().__init__(gguf, flags, log_path, served_name)
        self.cmd = [binary, "-m", gguf, "--port", str(PORT), "--alias", served_name, *flags]


def install_llamacpp(st: Stage, tag: str) -> dict:
    """Prebuilt llama.cpp CUDA 12.8 x64 release + its cudart bundle (GitHub release assets)."""
    base = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}"
    d = "/tmp/llamacpp"
    t0 = time.time()
    rc, out = sh(f"mkdir -p {d} && cd {d} && curl -sSfL -o a.tgz {base}/llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz && "
                 f"curl -sSfL -o b.tgz {base}/cudart-llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz && "
                 f"tar xzf a.tgz && tar xzf b.tgz && find {d} -name llama-server -o -name llama-perplexity -o -name 'libcudart*'",
                 timeout=900, out=st.logs / "llamacpp-install.txt")
    found = out.split()
    server = next((p for p in found if p.endswith("/llama-server")), None)
    ppl = next((p for p in found if p.endswith("/llama-perplexity")), None)
    libdirs = sorted({str(Path(p).parent) for p in found if "libcudart" in p} | ({str(Path(server).parent)} if server else set()))
    os.environ["LD_LIBRARY_PATH"] = ":".join(libdirs + [os.environ.get("LD_LIBRARY_PATH", "")])
    rc2, ver = sh([server, "--version"], timeout=60) if server else (1, "no llama-server")
    return {"llamacpp_tag": tag, "install_rc": rc, "install_s": round(time.time() - t0, 1), "llama_server": server,
            "llama_perplexity": ppl, "llama_server_version": ver.strip()[-400:], "version_rc": rc2}


def wikitext_file(st: Stage) -> Path:
    p = st.dir / "wikitext2_test.txt"
    if not p.exists():
        from datasets import load_dataset
        ds = load_dataset("Salesforce/wikitext", "wikitext-2-raw-v1", split="test")
        p.write_text("".join(ds["text"]))
    return p


def ppl_vllm(base_url: str, served: str, tokenizer_repo: str, text_path: Path, ctx: int, chunks: int) -> dict:
    """Perplexity over the OpenAI-compatible vLLM endpoint with prompt_logprobs: the text is tokenized
    once, cut into `chunks` non-overlapping windows of `ctx` tokens, and only the second half of each
    window is scored (each scored token sees >= ctx/2 tokens of context) - the same windowing as llama-perplexity."""
    import math
    import httpx
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(tokenizer_repo)
    ids = tok(text_path.read_text(), add_special_tokens=False)["input_ids"]
    nll, n = 0.0, 0
    with httpx.Client(timeout=600) as c:
        for k in range(min(chunks, len(ids) // ctx)):
            win = ids[k * ctx:(k + 1) * ctx]
            r = c.post(base_url + "/v1/completions", json={"model": served, "prompt": win, "max_tokens": 1,
                                                           "temperature": 0, "prompt_logprobs": 0})
            r.raise_for_status()
            plp = r.json()["choices"][0]["prompt_logprobs"]
            for pos in range(ctx // 2 + 1, ctx):   # = llama-perplexity: first = n_ctx/2, predicts tokens first+1..n_ctx-1
                entry = plp[pos] or {}
                lp = entry.get(str(win[pos]))
                nll -= lp["logprob"] if isinstance(lp, dict) else lp
                n += 1
    return {"ppl": round(math.exp(nll / n), 4), "ppl_tokens_scored": n, "ppl_ctx": ctx, "ppl_chunks": chunks,
            "ppl_method": "vLLM prompt_logprobs, second half of each window", "ppl_tokens_total": len(ids)}


def ppl_llamacpp(binary: str, gguf: str, text_path: Path, ctx: int, chunks: int, logs: Path, name: str) -> dict:
    rc, out = sh([binary, "-m", gguf, "-f", str(text_path), "-c", str(ctx), "--chunks", str(chunks), "-ngl", "99"],
                 timeout=1800, out=logs / f"llama-perplexity-{name}.txt", env=dict(os.environ, CUDA_VISIBLE_DEVICES="0"))
    m = re.search(r"Final estimate: PPL = ([\d.]+) \+/- ([\d.]+)", out)
    return {"ppl": float(m.group(1)), "ppl_stderr": float(m.group(2)), "ppl_ctx": ctx, "ppl_chunks": chunks,
            "ppl_method": "llama-perplexity"} if m else {"ppl_rc": rc, "ppl_error": out[-800:]}


def lm_eval(st: Stage, served: str, tokenizer_repo: str, tasks: str, limit: int, name: str, version: str) -> dict:
    """lm-eval (own venv, so it can't change vLLM's packages) against the OpenAI-compatible /v1/completions."""
    venv = "/tmp/lmeval"
    if not Path(venv, "bin", "lm_eval").exists():
        rc, out = sh(f"{sys.executable} -m pip install -q uv && uv venv -q {venv} && uv pip install -q --python {venv}/bin/python "
                     f"'lm-eval[api]=={version}' --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match",
                     timeout=1500, out=st.logs / "lmeval-install.txt")
        if rc:
            return {"lmeval_install_rc": rc, "lmeval_error": out[-800:]}
    out_dir = st.dir / f"lmeval-{name}"
    args = (f"model={served},base_url=http://127.0.0.1:{PORT}/v1/completions,num_concurrent=8,max_retries=3,"
            f"tokenized_requests=False,tokenizer_backend=huggingface,tokenizer={tokenizer_repo}")
    cmd = [f"{venv}/bin/lm_eval", "--model", "local-completions", "--model_args", args, "--tasks", tasks,
           "--limit", str(limit), "--output_path", str(out_dir)]
    t0 = time.time()
    rc, out = sh(cmd, timeout=3600, out=st.logs / f"lmeval-{name}.txt")
    row: dict = {"lmeval_cmd": shlex.join(cmd), "lmeval_rc": rc, "lmeval_s": round(time.time() - t0, 1),
                 "lmeval_version": version, "lmeval_limit": limit}
    res = sorted(out_dir.rglob("results_*.json"))
    if res:
        j = json.loads(res[-1].read_text())
        row["lmeval"] = {t: {k: v for k, v in m.items() if k != "alias"} for t, m in j.get("results", {}).items()}
    else:
        row["lmeval_tail"] = out[-1500:]
    return row


def stage_quant(a) -> None:
    """Task 5: FP16 vs AWQ (vLLM) vs GGUF Q8_0 / Q4_K_M (llama.cpp CUDA): decode, c=16, perplexity, lm-eval."""
    st = Stage("quant")
    inst = install_pinned(st, a.vllm_version)
    text = wikitext_file(st)
    done = st.done()
    from huggingface_hub import hf_hub_download, list_repo_files
    variants = [("fp16", "vllm", a.fp16_model), ("awq-int4", "vllm", a.awq_model),
                ("gguf-q8_0", "llamacpp", "q8_0"), ("gguf-q4_k_m", "llamacpp", "q4_k_m")]
    lcpp: dict | None = None
    for name, engine, ref in variants:
        if name not in a.variants.split(","):
            continue
        parts = [p for p in ("decode", "c16", "ppl", "lmeval") if f"{name}-{p}" not in done]
        if not parts:
            continue
        if engine == "vllm":
            flags = ["--dtype", "half", "--gpu-memory-utilization", "0.9", "--max-model-len", "4096", "--no-enable-prefix-caching"]
            srv = VllmServer(ref, flags, st.logs / f"server-{name}.log", served_name=name)
            prov = {"model": ref, "model_revision": model_revision(ref), "engine": f"vLLM {a.vllm_version}",
                    "serving_flags": flags, "vllm_version": a.vllm_version, "torch": inst["torch_after_install"]}
            api = "openai"
        else:
            if lcpp is None:
                lcpp = install_llamacpp(st, a.llamacpp_tag)
                st.write("llamacpp-install", {"kind": "install", **lcpp})
            if not lcpp.get("llama_server"):
                st.write(f"{name}-skipped", {"kind": "skipped", "reason": "llama.cpp CUDA binary not available", **lcpp})
                continue
            fname = next(f for f in list_repo_files(a.gguf_repo) if f.lower().endswith(f"{ref}.gguf"))
            gguf = hf_hub_download(a.gguf_repo, fname)
            flags = ["-ngl", "99", "-c", "8192", "-np", "16", "--metrics", "--no-webui"]
            srv = LlamaCppServer(lcpp["llama_server"], gguf, flags, st.logs / f"server-{name}.log", served_name=name)
            prov = {"model": f"{a.gguf_repo}/{fname}", "model_revision": model_revision(a.gguf_repo),
                    "engine": f"llama.cpp {a.llamacpp_tag} (CUDA 12.8 prebuilt)", "serving_flags": flags}
            api = "llamacpp"
        with srv:
            res = srv.start()
            if not res["started"]:
                st.write(f"{name}-server", {"kind": "server_fail", **res, "error_lines": error_lines(srv.log_text())}, **prov)
                continue
            startup = {k: v for k, v in parse_startup(srv.log_text()).items() if k != "startup_lines"} if engine == "vllm" else {}
            if "decode" in parts:
                dec = batch1_decode(srv.base_url, name, a.decode_runs, a.decode_max_tokens, st.dir / f"{name}-decode-gpu")
                st.write(f"{name}-decode", {"kind": "decode_batch1", "variant": name, **dec, **startup}, **prov,
                         client={"endpoint": "/v1/chat/completions", "stream": True, "ignore_eos": True,
                                 "max_tokens": a.decode_max_tokens, "runs": a.decode_runs})
            if "c16" in parts:
                cc = client_cfg(name, 16, 64)
                if api == "llamacpp":
                    cc |= {"api": "llamacpp", "endpoint": "/completion"}
                row = harness_point(srv.base_url, cc, st.dir / f"{name}-c16", st.dir / f"{name}-c16" / "gpu.csv")
                st.write(f"{name}-c16", {"kind": "closed_loop", "variant": name, "concurrency": 16, **row}, **prov, client=cc)
            if "ppl" in parts:
                try:
                    if engine == "vllm":
                        p = ppl_vllm(srv.base_url, name, a.fp16_model, text, a.ppl_ctx, a.ppl_chunks)
                    else:   # llama-perplexity loads the model itself: free the GPU, then bring the server back
                        srv.stop()
                        p = ppl_llamacpp(lcpp["llama_perplexity"], gguf, text, a.ppl_ctx, a.ppl_chunks, st.logs, name)
                        srv.start()
                except Exception as exc:
                    p = {"ppl_error": f"{type(exc).__name__}: {exc}"}
                st.write(f"{name}-ppl", {"kind": "perplexity", "variant": name, "text": "wikitext-2-raw-v1 test (Salesforce/wikitext)", **p}, **prov)
            if "lmeval" in parts and srv.proc and srv.proc.poll() is None:
                row = lm_eval(st, name, a.fp16_model, a.lmeval_tasks, a.lmeval_limit, name, a.lmeval_version)
                st.write(f"{name}-lmeval", {"kind": "lmeval", "variant": name, **row}, **prov)


STAGE_ARGS["quant"] = [
    lambda p: p.add_argument("--vllm-version", required=True),
    lambda p: p.add_argument("--fp16-model", default="Qwen/Qwen2.5-3B-Instruct"),
    lambda p: p.add_argument("--awq-model", default="Qwen/Qwen2.5-3B-Instruct-AWQ"),
    lambda p: p.add_argument("--gguf-repo", default="Qwen/Qwen2.5-3B-Instruct-GGUF"),
    lambda p: p.add_argument("--llamacpp-tag", default="b11146"),
    lambda p: p.add_argument("--variants", default="fp16,awq-int4,gguf-q8_0,gguf-q4_k_m"),
    lambda p: p.add_argument("--decode-runs", type=int, default=5),
    lambda p: p.add_argument("--decode-max-tokens", type=int, default=256),
    lambda p: p.add_argument("--ppl-ctx", type=int, default=512),
    lambda p: p.add_argument("--ppl-chunks", type=int, default=40),
    lambda p: p.add_argument("--lmeval-tasks", default="gsm8k,hellaswag"),
    lambda p: p.add_argument("--lmeval-limit", type=int, default=250),
    lambda p: p.add_argument("--lmeval-version", default="0.4.12"),
]

STAGES = {"smoke": stage_smoke, "baseline": stage_baseline, "kvgrid": stage_kvgrid, "sweep": stage_sweep,
          "quant": stage_quant}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    a, rest = ap.parse_known_args()
    sub = argparse.ArgumentParser(prog=f"--stage {a.stage}")
    for add in STAGE_ARGS.get(a.stage, []):
        add(sub)
    a = argparse.Namespace(**vars(a), **vars(sub.parse_args(rest)))
    log(f"stage {a.stage} start (run {RUN_ID}, git {GIT_SHA})")
    t0 = time.time()
    try:
        STAGES[a.stage](a)
    except Exception:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / a.stage / "stage_error.txt").write_text(traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
    finally:
        (RESULTS / a.stage).mkdir(parents=True, exist_ok=True)
        (RESULTS / a.stage / "stage.json").write_text(json.dumps(
            {"stage": a.stage, "run_id": RUN_ID, "git_sha": GIT_SHA, "runtime_s": round(time.time() - t0, 1),
             "args": {k: v for k, v in vars(a).items()}}, indent=2, default=str) + "\n")
        log(f"stage {a.stage} end after {time.time() - t0:.0f} s")



if __name__ == "__main__":
    main()
