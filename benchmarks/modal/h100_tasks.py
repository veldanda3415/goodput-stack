"""H100 build tasks; runs INSIDE a Modal H100 container (benchmarks/modal/h100_app.py starts it).

    python -m benchmarks.modal.h100_tasks --task h0|h1|h2|h3|h4|h5 [--budget-h H] [task options]

Reuses the T4 machinery in benchmarks/kaggle/t4_notebook.py (Stage, offline_point, probe_tools, VllmServer, http_run,
samplers) with label "Modal H100 SXM, real" and --dtype bfloat16 unless a row says otherwise. Output:
$GOODPUT_RESULTS/<task>/<task>.jsonl (one row per measurement, with provenance) + raw logs, sampler CSVs, traces.
Profiler traces are analysed locally afterwards (benchmarks/kaggle/trace_breakdown.py), not on the billed GPU.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time
import traceback
from pathlib import Path

from benchmarks.kaggle import t4_notebook as nb

LABEL = "Modal H100 SXM, real"
nb.RIDGE_LABEL = LABEL   # offline_point / http_run rows
DTYPE = "bfloat16"
REVS = json.loads(Path("/hf/revisions.json").read_text()) if Path("/hf/revisions.json").exists() else {}
QWEN = "Qwen/Qwen2.5-3B-Instruct"
LLAMA = "meta-llama/Llama-3.1-8B-Instruct"
LLAMA_FP8 = "RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8"
SWEEP = [64, 128, 256, 384, 512, 1024, 2048]
PROFILE_WINDOW = (300, 300)   # (delay_iterations, max_iterations) of vLLM's torch profiler


def rev(repo: str) -> str:
    return REVS[repo]["revision"]


def cfg_path(repo: str) -> str:
    return f"/hf/hub/models--{repo.replace('/', '--')}/snapshots/{rev(repo)}/config.json"


def modal_env() -> dict:
    return {k: v for k, v in sorted(os.environ.items()) if k.startswith("MODAL_") and "TOKEN" not in k and "SECRET" not in k}


def gpu_identity(st: nb.Stage) -> dict:
    q = "name,uuid,driver_version,pci.bus_id,power.limit,power.max_limit,clocks.max.sm,clocks.max.mem,memory.total,mig.mode.current,ecc.mode.current"
    rc, out = nb.sh(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader"], timeout=60, out=st.logs / "gpu-identity.txt")
    vals = [x.strip() for x in out.strip().splitlines()[0].split(",")] if rc == 0 and out.strip() else []
    # driver 610's plain `nvidia-smi` header no longer matches env_info's "CUDA Version:" pattern; -q still lists it
    m = re.search(r"CUDA Version\s*:\s*([\d.]+)", nb.sh(["nvidia-smi", "-q"], timeout=60)[1])
    return dict(zip(q.split(","), vals)) | {"cuda_driver": m.group(1) if m else st.env.get("cuda_version_driver")}


def provenance(st: nb.Stage, model: str) -> dict:
    gid = getattr(st, "_gid", None) or gpu_identity(st)
    st._gid = gid
    return {"label": LABEL, "model": model, "model_revision": rev(model), "vllm_version": st.env.get("pkg_vllm"),
            "torch": st.env.get("pkg_torch"), "gpu_name": gid.get("name"), "gpu_uuid": gid.get("uuid"),
            "driver": gid.get("driver_version"), "power_limit_w": gid.get("power.limit"), "cuda_driver": gid.get("cuda_driver"),
            "modal_task_id": os.environ.get("MODAL_TASK_ID"), "modal_region": os.environ.get("MODAL_REGION"),
            "modal_cloud": os.environ.get("MODAL_CLOUD_PROVIDER"), "flag_source": "logs/vllm-bench-throughput-help.txt (H0)"}


TIMING_RE = re.compile(r"(took|takes|finished in|Loading weights|init engine|Graph capturing|torch\.compile|Compiling|"
                       r"Starting vLLM|Application startup complete|Available KV cache|GPU KV cache size|backend)", re.I)


def timing_lines(text: str, n: int = 40) -> list[str]:
    return [l.strip()[-280:] for l in text.splitlines() if TIMING_RE.search(l)][:n]


class Runner:
    """offline_point with the H100 defaults, a budget guard and wall-clock bookkeeping."""

    def __init__(self, st: nb.Stage, a):
        self.st, self.a = st, a
        self.done = st.done()

    def left_h(self) -> float:
        return nb.budget_left_h(self.a.budget_h)

    def off(self, key: str, model: str, mns: int, n_prompts: int, in_len: int, out_len: int, warmups: int = 32,
            extra: list[str] | None = None, env: dict | None = None, dtype: str = DTYPE, need_h: float = 0.05,
            reserve_h: float = 0.0, util: float = 0.95, **row_extra) -> dict | None:
        if key in self.done:
            rows = [r for r in self.st.rows() if r.get("key") == key]
            return rows[-1] if rows else None
        left = self.left_h()
        if left < need_h + reserve_h:
            self.st.write(f"skip-{key}", {"kind": "skipped", "item": key, "reason": f"budget: {left:.3f} h left, need {need_h} + reserve {reserve_h:.2f}"},
                          **provenance(self.st, model))
            return None
        t0 = time.time()
        extra = list(extra or [])
        # vLLM 0.31.0 picks max_num_batched_tokens 16,384 for the offline LLM class on this 80 GB GPU (log: "Chunked
        # prefill is enabled with max_num_batched_tokens=16384"); the T4 workload is 8,192, so it is always explicit
        if "--max-num-batched-tokens" not in extra:
            extra = ["--max-num-batched-tokens", "8192"] + extra
        r = nb.offline_point(self.st, key, model, rev(model), mns, n_prompts, in_len, out_len, util, warmups,
                             max(300.0, (left - reserve_h) * 3600), provenance(self.st, model), extra_args=extra, gpu=0,
                             gpu_interval_s=0.5, env_extra=env, dtype=dtype, label=LABEL,
                             row_extra=row_extra)
        wall = time.time() - t0
        el = (r.get("bench_json") or {}).get("elapsed_time")
        text = (self.st.logs / f"{key}.log").read_text(errors="replace")
        extra_row = {"proc_wall_s": round(wall, 1), "bench_elapsed_s": el,
                     "start_and_teardown_s": round(wall - el, 1) if el else None,
                     "attention_backend": nb.default_backend(text), "timing_lines": timing_lines(text)}
        self.st.write(f"{key}-wall", {"kind": "wall", "of": key, **extra_row}, **provenance(self.st, model))
        r |= extra_row
        self.done.add(key)
        return r

    def profile(self, key: str, model: str, mns: int, extra: list[str] | None = None, dtype: str = DTYPE, **kw) -> dict | None:
        delay, iters = PROFILE_WINDOW
        tdir = self.st.dir / f"trace-{key}"
        pc = {"profiler": "torch", "torch_profiler_dir": str(tdir), "torch_profiler_with_stack": False,
              "torch_profiler_record_shapes": False, "torch_profiler_use_gzip": True, "detailed_trace_annotation": True,
              "ignore_frontend": True, "delay_iterations": delay, "max_iterations": iters}
        return self.off(key, model, mns, 4 * mns, 128, 256, 32, list(extra or []) + ["--profile", "--profiler-config", json.dumps(pc)],
                        env={"VLLM_CUSTOM_SCOPES_FOR_PROFILING": "1"}, dtype=dtype, profiler_config=pc,
                        profiler_note="tok/s of this run include profiler overhead and the trace export; use unprofiled rows for speed",
                        **kw)

    def sweep(self, tag: str, model: str, extra: list[str] | None = None, mns_list: list[int] = SWEEP, need_h: float = 0.06,
              reserve_h: float = 0.0, skip_mns: dict | None = None, **kw) -> dict:
        """Climb max-num-seqs; stop once output tok/s falls twice in a row. skip_mns: mns -> an existing row to reuse."""
        res: dict = {}
        prev, falls = None, 0
        for mns in mns_list:
            r = (skip_mns or {}).get(mns) or self.off(f"{tag}-mns{mns}", model, mns, 4 * mns, 128, 256, 32, extra,
                                                      need_h=need_h, reserve_h=reserve_h, sweep=tag, **kw)
            if r is None:
                break
            res[mns] = r
            v = r.get("output_tok_s")
            if v is None:
                falls += 1
            elif prev is not None and v < prev:
                falls += 1
            else:
                falls = 0
            prev = v if v is not None else prev
            if falls >= 2:
                self.st.write(f"{tag}-stop", {"kind": "sweep_stop", "at_mns": mns, "reason": "output tok/s fell twice in a row"},
                              **provenance(self.st, model))
                break
        best = max((m for m in res if res[m].get("output_tok_s")), key=lambda m: res[m]["output_tok_s"], default=None)
        self.st.write(f"{tag}-best", {"kind": "sweep_best", "sweep": tag, "best_mns": best,
                                      "best_output_tok_s": res[best]["output_tok_s"] if best else None,
                                      "points": {m: res[m].get("output_tok_s") for m in res}}, **provenance(self.st, model))
        return {"best": best, "rows": res}


# ---------------------------------------------------------------- H0

def task_h0(st: nb.Stage, a) -> None:
    L = st.logs
    sysinfo = nb.system_info(L)
    nb.sh(["nvidia-smi", "-q"], timeout=60, out=L / "nvidia-smi-q-full.txt")
    nb.sh("cat /proc/cpuinfo | grep -m1 'model name'; nproc; cat /sys/fs/cgroup/cpu.max 2>/dev/null; "
          "cat /sys/fs/cgroup/memory.max 2>/dev/null; free -g", timeout=30, out=L / "cpu-ram.txt")
    nb.sh(["nvidia-smi", "topo", "-m"], timeout=60, out=L / "nvidia-smi-topo.txt")
    nb.sh(["pip", "freeze"], timeout=120, out=L / "pip-freeze.txt")
    nb.sh(["vllm", "collect-env"], timeout=300, out=L / "vllm-collect-env.txt")
    for name, cmd in (("vllm-bench-throughput-help", ["vllm", "bench", "throughput", "--help=all"]),
                      ("vllm-serve-help", ["vllm", "serve", "--help=all"])):
        nb.sh(cmd, timeout=300, out=L / f"{name}.txt")
    st.write("system", {"kind": "system", **sysinfo, "env": st.env, "gpu": gpu_identity(st), "modal_env": modal_env(),
                        "cpu_ram": (L / "cpu-ram.txt").read_text()[-600:]})
    r = nb.probe_tools(st, 0)
    st.write("tools", {"kind": "tools", **r}, **provenance(st, QWEN))
    # 30 s idle sampler
    from benchmarks.gpu_sampler import GpuSampler, summarize
    with GpuSampler(st.dir / "idle.gpu.csv", 0.5, 0):
        time.sleep(30)
    st.write("idle", {"kind": "idle", "seconds": 30, **summarize(st.dir / "idle.gpu.csv"),
                      "fields": json.loads((st.dir / "idle.gpu.csv.fields.json").read_text())}, **provenance(st, QWEN))
    # vllm serve smoke: start, one request, stop
    flags = ["--revision", rev(QWEN), "--dtype", DTYPE, "--gpu-memory-utilization", "0.95", "--max-num-seqs", "384",
             "--max-num-batched-tokens", "8192", "--no-enable-prefix-caching"]
    srv = nb.VllmServer(QWEN, flags, L / "serve-smoke.log")
    t0 = time.time()
    res = srv.start(timeout_s=900)
    t_ready = time.time()
    req = nb.chat(srv.base_url, QWEN, "Say hello in five words.", 32, stream=True) if res.get("started") else {}
    srv.stop()
    t_stop = time.time()
    text = srv.log_text()
    st.write("serve-smoke", {"kind": "serve_smoke", "cmd": shlex.join(srv.cmd), **res, "t_start_unix": round(t0, 3),
                             "ready_s": round(t_ready - t0, 1), "stop_s": round(t_stop - t_ready, 1), "request": req,
                             **{k: v for k, v in nb.parse_startup(text).items() if k != "startup_lines"},
                             "attention_backend": nb.default_backend(text), "timing_lines": timing_lines(text, 60),
                             "error_lines": nb.error_lines(text) if not res.get("started") else []},
             **provenance(st, QWEN))


# ---------------------------------------------------------------- H1

def task_h1(st: nb.Stage, a) -> None:
    # H0's ncu attempt failed on clock locking; retry with --clock-control none (does it give counters then?), and ask
    # nsys for GPU metrics (also counter-based)
    tiny = [sys.executable, "-c", nb.TINY_CUDA_PY]
    for key, cmd in (("ncu-noclock", ["ncu", "--clock-control", "none", "--metrics",
                                      "sm__throughput.avg.pct_of_peak_sustained_elapsed,dram__throughput.avg.pct_of_peak_sustained_elapsed",
                                      "-c", "3", *tiny]),
                     ("nsys-gpu-metrics", ["nsys", "profile", "-f", "true", "-o", "/tmp/nsys-gm", "--gpu-metrics-devices=0", *tiny])):
        rc, text = nb.sh(cmd, timeout=300, out=st.logs / f"{key}.txt")
        st.write(key, {"kind": "tool_probe", "cmd": shlex.join(cmd), "rc": rc, "tail": text.strip()[-1200:]}, **provenance(st, QWEN))
    d = st.dir / "micro"
    cmd = [sys.executable, "-m", "benchmarks.microbench.gpu_ceilings", "--nvml-index", "0", "--out", str(d),
           "--label", LABEL, "--bw-gib", "4", "--bw-repeats", "20", "--dtypes", "bfloat16,fp8",
           "--gemm-dtypes", "bfloat16,fp8,fp8fast,float16", "--sustain-s", "60", "--m-list", "1,16,64,256,512,1024,2048,8192",
           "--shape-min-s", str(a.shape_min_s), "--interval", "0.25",
           "--model-config", f"llama3.1-8b={cfg_path(LLAMA)}", "--model-config", f"qwen2.5-3b={cfg_path(QWEN)}"]
    t0 = time.time()
    rc, text = nb.sh(cmd, timeout=max(300.0, nb.budget_left_h(a.budget_h) * 3600), out=st.logs / "micro.log",
                     env=dict(os.environ, CUDA_VISIBLE_DEVICES="0"))
    st.write("micro", {"kind": "micro", "rc": rc, "cmd": shlex.join(cmd), "wall_s": round(time.time() - t0, 1),
                       "log_tail": text.strip()[-1500:] if rc else ""}, **provenance(st, QWEN))


# ---------------------------------------------------------------- H2

def task_h2(st: nb.Stage, a) -> None:
    R = Runner(st, a)
    END = 0.07   # reserve for the end reference point (h)
    ref = R.off("ref-start", QWEN, 384, 4 * 384, 128, 256, ref_tag="start", part="H2")
    sw = R.sweep("sweep", QWEN, skip_mns={384: ref} if ref else None, reserve_h=END, part="H2")
    best = sw["best"] or 384
    for mbt in (16384, 32768):
        R.off(f"mbt{mbt}-mns{best}", QWEN, best, 4 * best, 128, 256, extra=["--max-num-batched-tokens", str(mbt)],
              reserve_h=END, part="H2", ablation="max-num-batched-tokens")
    R.off(f"half-mns{best}", QWEN, best, 4 * best, 128, 256, dtype="half", reserve_h=END, part="H2", ablation="dtype half")
    R.off(f"eager-mns{best}", QWEN, best, 4 * best, 128, 256, extra=["--enforce-eager"], reserve_h=END, part="H2",
          ablation="enforce-eager")
    if best > 512:   # default capture sizes end at 512 (vllm bench throughput --help=all, --max-cudagraph-capture-size)
        R.off(f"cg{best}-mns{best}", QWEN, best, 4 * best, 128, 256, extra=["--max-cudagraph-capture-size", str(best)],
              reserve_h=END, part="H2", ablation="CUDA graphs up to max-num-seqs")
    for mns in sorted({64, 384, best}):
        R.profile(f"prof-mns{mns}", QWEN, mns, reserve_h=END, need_h=0.07, part="H2")
    R.off("ref-end", QWEN, 384, 4 * 384, 128, 256, ref_tag="end", part="H2", need_h=0.0)


# ---------------------------------------------------------------- H3

def save_configs(st: nb.Stage) -> None:
    """config.json of every model into the results (the HF snapshot files are symlinks the volume CLI cannot fetch)."""
    for repo in (QWEN, LLAMA, LLAMA_FP8):
        try:
            (st.logs / f"config-{repo.replace('/', '--')}.json").write_text(Path(cfg_path(repo)).read_text())
        except OSError as exc:
            nb.log(f"config of {repo}: {exc!r}")


def task_h3(st: nb.Stage, a) -> None:
    save_configs(st)
    R = Runner(st, a)
    configs = {"a-bf16": (LLAMA, []), "b-fp8": (LLAMA_FP8, []), "c-fp8kv": (LLAMA_FP8, ["--kv-cache-dtype", "fp8"])}
    wanted = [c.strip() for c in a.configs.split(",")]
    bests = {}
    # profiles at the end need ~0.15 h; keep them unless a sweep has nowhere else to go
    for i, tag in enumerate(wanted):
        model, extra = configs[tag]
        reserve = 0.16 if a.profile else 0.0
        sw = R.sweep(tag, model, extra, mns_list=[int(x) for x in a.mns.split(",")], reserve_h=reserve, need_h=0.07,
                     part="H3", config=tag)
        bests[tag] = sw["best"]
    if a.profile:
        for tag in ("a-bf16", "c-fp8kv"):
            if bests.get(tag):
                model, extra = configs[tag]
                R.profile(f"prof-{tag}-mns{bests[tag]}", model, bests[tag], extra, need_h=0.07, part="H3", config=tag)


# ---------------------------------------------------------------- H4

def task_h4(st: nb.Stage, a) -> None:
    R = Runner(st, a)
    kv = {"a-bf16": (LLAMA, [], a.kv_bf16, a.best_bf16), "c-fp8kv": (LLAMA_FP8, ["--kv-cache-dtype", "fp8"], a.kv_fp8kv, a.best_fp8kv)}
    # 1. long context at the best max-num-seqs, or the largest that fits the KV pool without preemption
    for in_len in (2048, 8192):
        for tag, (model, extra, kv_tokens, best) in kv.items():
            fit = kv_tokens // (in_len + 256)
            mns = max(1, min(best, fit))
            R.off(f"long{in_len}-{tag}-mns{mns}", model, mns, 4 * mns, in_len, 256, 8, extra, part="H4.1", config=tag,
                  kv_tokens_pool=kv_tokens, mns_rule=f"min(best {best}, KV pool {kv_tokens} // ({in_len} + 256) = {fit})")
    model, extra, kv_tokens, best = kv["a-bf16"]
    # 2. decode-only and prefill-only (BF16)
    fit = kv_tokens // (16 + 512)
    mns = min(best, fit)
    R.off(f"dec-a-bf16-mns{mns}", LLAMA, mns, 2 * mns, 16, 512, 16, part="H4.2", config="a-bf16",
          mns_rule=f"min(best {best}, KV pool {kv_tokens} // 528 = {fit})")
    R.off("pre-a-bf16-in2048", LLAMA, best, a.pre_prompts, 2048, 1, 4, part="H4.2", config="a-bf16")
    # 3. enforce-eager (BF16)
    for m in sorted({64, best}):
        R.off(f"eager-a-bf16-mns{m}", LLAMA, m, 4 * m, 128, 256, extra=["--enforce-eager"], part="H4.3", config="a-bf16")
    # 4. prefix caching on / off, shared 1,024-token prefix (BF16, best max-num-seqs)
    for on in (True, False):
        flag = "--enable-prefix-caching" if on else "--no-enable-prefix-caching"
        R.off(f"prefix-{'on' if on else 'off'}-a-bf16-mns{best}", LLAMA, best, 4 * best, 128, 256,
              extra=[*a.prefix_args.split(), flag], part="H4.4", config="a-bf16", prefix_caching=on,
              note="offline_point puts --no-enable-prefix-caching first; the later flag here wins (argparse: last one)")


# ---------------------------------------------------------------- H5

def task_h5(st: nb.Stage, a) -> None:
    import psutil
    model = LLAMA_FP8
    extra = ["--kv-cache-dtype", "fp8"] if a.fp8kv else []
    prov = provenance(st, model)
    R = Runner(st, a)
    # offline at the same max-num-seqs and the same request shape (output 128 +/- 25 %), for the served / offline ratio
    R.off(f"offline-mns{a.mns}-256-128", model, a.mns, 4 * a.mns, 256, 128, 32,
          extra + ["--random-range-ratio", "0.25"], part="H5", reserve_h=0.3,
          note="--random-range-ratio 0.25 jitters input and output lengths by +/- 25 % (the later flag wins)")
    flags = ["--revision", rev(model), "--dtype", DTYPE, "--gpu-memory-utilization", "0.95", "--max-num-seqs", str(a.mns),
             "--max-num-batched-tokens", "8192", "--no-enable-prefix-caching", *extra]
    srv = nb.VllmServer(model, flags, st.logs / "serve.log")
    res = srv.start(timeout_s=900)
    text = srv.log_text()
    st.write("serve-start", {"kind": "serve_start", "cmd": shlex.join(srv.cmd), **res,
                             **{k: v for k, v in nb.parse_startup(text).items() if k != "startup_lines"},
                             "timing_lines": timing_lines(text, 60)}, **prov)
    if not res.get("started"):
        st.write("serve-error", {"kind": "error", "error_lines": nb.error_lines(text)}, **prov)
        return
    try:
        nb.chat(srv.base_url, model, "warm up", 16, stream=True)
        for users in [int(x) for x in a.users.split(",")]:
            if nb.budget_left_h(a.budget_h) < 0.04:
                st.write(f"skip-u{users}", {"kind": "skipped", "reason": "budget"}, **prov)
                break
            procs = 1 if users <= a.single_proc_max else a.procs
            nb.http_run(st, f"http-u{users}-p{procs}", srv, model, users, procs, 256, 128, a.req_per_user,
                        prov | {"server_flags": flags}, max_tokens_jitter=0.25, label=LABEL)
        if a.client_check and nb.budget_left_h(a.budget_h) > 0.04:
            u = a.client_check
            nb.http_run(st, f"http-u{u}-p1", srv, model, u, 1, 256, 128, a.req_per_user, prov | {"server_flags": flags,
                        "purpose": "client-bottleneck check: one client process"}, max_tokens_jitter=0.25, label=LABEL)
    finally:
        srv.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--budget-h", type=float, default=0.1)
    ap.add_argument("--shape-min-s", type=float, default=1.5)
    ap.add_argument("--configs", default="a-bf16,b-fp8,c-fp8kv")
    ap.add_argument("--mns", default="64,128,256,384,512,1024,2048")
    ap.add_argument("--profile", type=int, default=1)
    ap.add_argument("--best-bf16", type=int, default=512)
    ap.add_argument("--best-fp8kv", type=int, default=512)
    ap.add_argument("--kv-bf16", type=int, default=0)
    ap.add_argument("--kv-fp8kv", type=int, default=0)
    ap.add_argument("--pre-prompts", type=int, default=512)
    ap.add_argument("--prefix-args", default="")
    ap.add_argument("--fp8kv", type=int, default=0)
    ap.add_argument("--users", default="16,64,128,256,512,1024")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--single-proc-max", type=int, default=128)
    ap.add_argument("--req-per-user", type=int, default=4)
    ap.add_argument("--client-check", type=int, default=0)
    a, _ = ap.parse_known_args()
    st = nb.Stage(a.task)
    fn = {"h0": task_h0, "h1": task_h1, "h2": task_h2, "h3": task_h3, "h4": task_h4, "h5": task_h5}[a.task]
    st.write("start", {"kind": "start", "argv": sys.argv, "budget_h": a.budget_h, "revisions": REVS, "modal_env": modal_env()})
    try:
        fn(st, a)
    except Exception as exc:
        st.write("error", {"kind": "error", "error": f"{type(exc).__name__}: {exc}"[:800], "traceback": traceback.format_exc()[-3000:]})
        raise
    finally:
        nb.sh(["nvidia-smi", "-rgc"], timeout=60, out=st.logs / "nvidia-smi-rgc-finally.txt")   # no-op unless a lock was set
        st.write("session", {"kind": "session", "session_h": round(nb.session_elapsed_h(), 4)})


if __name__ == "__main__":
    main()
