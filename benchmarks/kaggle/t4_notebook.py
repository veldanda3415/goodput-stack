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
    rc, out = sh([sys.executable, "-m", "pip", "install", "-q", f"vllm=={version}"], timeout=1500,
                 out=logs / f"pip-install-vllm-{version}.txt")
    rc2, ver = sh(["vllm", "--version"], timeout=180)
    rc3, torch_v = sh([sys.executable, "-c", "import torch;print(torch.__version__, torch.version.cuda)"], timeout=120)
    return {"vllm_version_requested": version, "pip_rc": rc, "pip_s": round(time.time() - t0, 1),
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
        self._f = open(self.log_path, "w")
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


def batch1_decode(base_url: str, model: str, runs: int, max_tokens: int) -> dict:
    """`runs` sequential streamed chat requests, same prompt, ignore_eos, temperature 0 -> median and spread."""
    import statistics
    chat(base_url, model, DECODE_PROMPT, 16, stream=True)   # warmup, discarded
    recs = [chat(base_url, model, DECODE_PROMPT, max_tokens, stream=True, ignore_eos=True) for _ in range(runs)]
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
        dec = batch1_decode(srv.base_url, model, a.decode_runs, a.decode_max_tokens)
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

STAGES = {"smoke": stage_smoke, "baseline": stage_baseline}


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
