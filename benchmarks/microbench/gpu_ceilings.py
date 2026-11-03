"""Hardware ceilings of one GPU without vLLM: memory bandwidth, a sustained large FP16 GEMM, Qwen2.5-3B layer GEMMs.

    CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 python -m benchmarks.microbench.gpu_ceilings --nvml-index 0 --out DIR
    ... --quick                       # smoke: short runs, fewer shapes

Writes DIR/microbench.jsonl (one row per measurement), DIR/gemm_sustained.csv (one row per timed chunk of the
sustained GEMM), DIR/gpu.csv (benchmarks/gpu_sampler.py, 2 Hz, NVML + nvidia-smi clocks / power / throttle reasons)
and nvidia-smi -q snapshots before and after. Every row carries the GPU clock / power / throttle-reason summary of its
own time window (from gpu.csv).

Timing: CUDA events around a chunk of back-to-back launches; per-launch time = chunk time / launches.
  bandwidth   copy  b -> a          bytes = 2 x size   (1 GiB fp32 tensors, 20 timed repeats, median)
              triad a = b + 2.0 c   bytes = 3 x size
  gemm        torch.matmul(A, B, out=C), 8192 x 8192 x 8192 fp16, for --sustain-s seconds; FLOP = 2 M N K
  shapes      torch.matmul(x[M, K], W[N, K].t(), out=y) fp16: the GEMM that torch.nn.functional.linear(x, W) (vLLM's
              unquantized linear layers) dispatches to;
              FLOP = 2 M N K; bytes = 2 (M K + N K + M N), the minimum traffic (CALCULATED: each operand read or
              written once); >= --shape-min-s per point (2 s: several 4 Hz clock samples per point)
Qwen2.5-3B-Instruct shapes (config.json @ aa8e7253: hidden 2048, 16 heads, 2 KV heads, head_dim 128, intermediate 11008,
vocab 151936): qkv 2048 -> 2048 + 2 x 256, o 2048 -> 2048, gate_up 2048 -> 2 x 11008, down 11008 -> 2048,
lm_head 2048 -> 151936.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

QWEN3B_SHAPES = {"qkv": (2048, 2560), "o": (2048, 2048), "gate_up": (2048, 22016), "down": (11008, 2048),
                 "lm_head": (2048, 151936)}   # name -> (K, N)
M_LIST = [1, 16, 64, 128, 256, 384, 512, 2048, 8192]


def gemm_flops(m: int, n: int, k: int) -> int:
    return 2 * m * n * k


def gemm_min_bytes(m: int, n: int, k: int, elem: int = 2) -> int:
    return elem * (m * k + n * k + m * n)


def time_chunks(fn, min_s: float, chunk_target_s: float = 0.1, max_chunks: int = 10_000) -> dict:
    """Run fn back to back in chunks of ~chunk_target_s until min_s; return per-call seconds per chunk (CUDA events)."""
    import torch
    for _ in range(3):
        fn()
    torch.cuda.synchronize()
    s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    s.record()
    fn()
    e.record()
    e.synchronize()
    one = max(s.elapsed_time(e) / 1e3, 1e-6)
    iters = max(1, int(chunk_target_s / one))
    per_call, t_end, total = [], [], 0.0
    while total < min_s and len(per_call) < max_chunks:
        s.record()
        for _ in range(iters):
            fn()
        e.record()
        e.synchronize()
        dt = s.elapsed_time(e) / 1e3
        per_call.append(dt / iters)
        t_end.append(time.time())
        total += dt
    return {"iters_per_chunk": iters, "per_call_s": per_call, "t_end_unix": t_end, "timed_s": round(total, 4)}


def window(gpu_csv: Path, t0: float, t1: float) -> dict:
    from benchmarks.gpu_sampler import summarize
    try:
        return summarize(gpu_csv, t0, t1)
    except FileNotFoundError:
        return {}


class Out:
    def __init__(self, d: Path, prov: dict):
        self.d, self.prov = d, prov
        self.path = d / "microbench.jsonl"

    def write(self, row: dict) -> dict:
        full = {**self.prov, **row}
        with open(self.path, "a") as f:
            f.write(json.dumps(full, default=str) + "\n")
        print(json.dumps({k: v for k, v in row.items() if not isinstance(v, (list, dict))}, default=str)[:300], flush=True)
        return full


def bandwidth(out: Out, gpu_csv: Path, repeats: int, gib: float) -> None:
    import torch
    n = int(gib * 2**30) // 4
    a = torch.empty(n, dtype=torch.float32, device="cuda")
    b = torch.rand(n, dtype=torch.float32, device="cuda")
    c = torch.rand(n, dtype=torch.float32, device="cuda")
    for name, fn, nbytes in (("copy", lambda: a.copy_(b), 2 * n * 4),
                             ("triad", lambda: torch.add(b, c, alpha=2.0, out=a), 3 * n * 4)):
        for _ in range(3):
            fn()
        torch.cuda.synchronize()
        times, t0 = [], time.time()
        s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        for _ in range(repeats):
            s.record()
            fn()
            e.record()
            e.synchronize()
            times.append(s.elapsed_time(e) / 1e3)
        t1 = time.time()
        gbs = [nbytes / t / 1e9 for t in times]
        out.write({"kind": "bandwidth", "op": name, "tensor_bytes": n * 4, "bytes_moved_per_op": nbytes, "repeats": repeats,
                   "gb_s_median": round(statistics.median(gbs), 2), "gb_s_max": round(max(gbs), 2),
                   "gb_s_min": round(min(gbs), 2), "op_ms": [round(t * 1e3, 3) for t in times],
                   "window_unix": [round(t0, 3), round(t1, 3)], **window(gpu_csv, t0, t1)})
    del a, b, c
    torch.cuda.empty_cache()


def gemm_sustained(out: Out, gpu_csv: Path, size: int, seconds: float) -> None:
    import torch
    a = torch.randn(size, size, dtype=torch.float16, device="cuda")
    b = torch.randn(size, size, dtype=torch.float16, device="cuda")
    c = torch.empty(size, size, dtype=torch.float16, device="cuda")
    fl = gemm_flops(size, size, size)
    t0 = time.time()
    r = time_chunks(lambda: torch.matmul(a, b, out=c), seconds, chunk_target_s=0.1)
    t1 = time.time()
    tf = [fl / t / 1e12 for t in r["per_call_s"]]
    rows = list(zip(r["t_end_unix"], r["per_call_s"], tf))
    with open(out.d / "gemm_sustained.csv", "w") as f:
        f.write("t_end_unix,t_rel_s,per_call_ms,tflops\n")
        for t, pc, x in rows:
            f.write(f"{t:.3f},{t - t0:.3f},{pc * 1e3:.4f},{x:.3f}\n")
    per_second = []
    for sec in range(int(seconds) + 1):
        xs = [x for t, _, x in rows if sec <= t - t0 < sec + 1]
        if xs:
            per_second.append({"second": sec, "tflops_mean": round(statistics.fmean(xs), 3), "chunks": len(xs),
                               **window(gpu_csv, t0 + sec, t0 + sec + 1)})
    tail = [x for t, _, x in rows if t - t0 >= 10]
    out.write({"kind": "gemm_sustained", "m": size, "n": size, "k": size, "dtype": "float16", "op": "torch.matmul(out=)",
               "flop_per_call": fl, "seconds": seconds, "iters_per_chunk": r["iters_per_chunk"], "chunks": len(rows),
               "tflops_first_chunk": round(tf[0], 3), "tflops_max_chunk": round(max(tf), 3),
               "tflops_first_1s": per_second[0]["tflops_mean"] if per_second else None,
               "tflops_median_after_10s": round(statistics.median(tail), 3) if tail else None,
               "tflops_median_all": round(statistics.median(tf), 3), "per_second": per_second,
               "window_unix": [round(t0, 3), round(t1, 3)], **window(gpu_csv, t0, t1),
               **{f"after10s_{k}": v for k, v in window(gpu_csv, t0 + 10, t1).items()}})
    del a, b, c
    torch.cuda.empty_cache()


def shapes(out: Out, gpu_csv: Path, m_list: list[int], names: list[str], min_s: float) -> None:
    import torch
    import torch.nn.functional as F
    for name in names:
        k, n = QWEN3B_SHAPES[name]
        w = (torch.randn(n, k, dtype=torch.float16, device="cuda") * 0.02)
        for m in m_list:
            x = torch.randn(m, k, dtype=torch.float16, device="cuda")
            y = torch.empty(m, n, dtype=torch.float16, device="cuda")
            fl, by = gemm_flops(m, n, k), gemm_min_bytes(m, n, k)
            t0 = time.time()
            # torch.matmul(x, w.t(), out=y) is what F.linear(x, w) dispatches to (addmm/mm with a transposed weight);
            # out= keeps the allocator out of the loop
            r = time_chunks(lambda: torch.matmul(x, w.t(), out=y), min_s)
            t1 = time.time()
            med = statistics.median(r["per_call_s"])
            ref = F.linear(x[:1], w)   # same dispatch path check (one call)
            out.write({"kind": "shape", "shape": name, "m": m, "k": k, "n": n, "flop_per_call": fl, "min_bytes_per_call": by,
                       "per_call_us_median": round(med * 1e6, 3), "tflops": round(fl / med / 1e12, 3),
                       "gb_s_calculated": round(by / med / 1e9, 2), "arith_intensity_calculated": round(fl / by, 2),
                       "chunks": len(r["per_call_s"]), "iters_per_chunk": r["iters_per_chunk"], "timed_s": r["timed_s"],
                       "linear_check_shape": list(ref.shape),
                       "window_unix": [round(t0, 3), round(t1, 3)], **window(gpu_csv, t0, t1)})
            del x, y
        del w
        torch.cuda.empty_cache()


def smi(args: list[str]) -> str:
    try:
        return subprocess.run(["nvidia-smi", *args], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return repr(exc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--nvml-index", type=int, default=0, help="nvidia-smi / NVML index of the GPU CUDA sees as device 0")
    ap.add_argument("--parts", default="bandwidth,gemm,shapes")
    ap.add_argument("--sustain-s", type=float, default=60)
    ap.add_argument("--gemm-size", type=int, default=8192)
    ap.add_argument("--bw-repeats", type=int, default=20)
    ap.add_argument("--bw-gib", type=float, default=1.0)
    ap.add_argument("--m-list", default=",".join(map(str, M_LIST)))
    ap.add_argument("--shapes", default=",".join(QWEN3B_SHAPES))
    ap.add_argument("--shape-min-s", type=float, default=2.0)
    ap.add_argument("--interval", type=float, default=0.25, help="sampler interval (s)")
    ap.add_argument("--quick", action="store_true", help="smoke: 10 s GEMM, 5 bw repeats, M 64,384 only, 0.3 s per shape")
    a = ap.parse_args()
    if a.quick:
        a.sustain_s, a.bw_repeats, a.m_list, a.shape_min_s = 10, 5, "64,384", 0.3
    import torch
    from benchmarks.gpu_sampler import GpuSampler, smi_snapshot
    a.out.mkdir(parents=True, exist_ok=True)
    props = torch.cuda.get_device_properties(0)
    idx = str(a.nvml_index)
    prov = {"label": "Kaggle T4, real", "tool": "benchmarks/microbench/gpu_ceilings.py", "nvml_index": a.nvml_index,
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"), "cuda_device_order": os.environ.get("CUDA_DEVICE_ORDER"),
            "torch": torch.__version__, "torch_cuda": torch.version.cuda, "device_name": props.name,
            "torch_device_uuid": str(getattr(props, "uuid", "")), "sm_count": props.multi_processor_count,
            "smi_uuid": smi(["-i", idx, "--query-gpu=uuid", "--format=csv,noheader"]),
            "smi_driver": smi(["-i", idx, "--query-gpu=driver_version", "--format=csv,noheader"]),
            "allow_fp16_reduced_precision_reduction": torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction,
            "git_sha": os.environ.get("GOODPUT_GIT_SHA"), "run_id": os.environ.get("GOODPUT_RUN_ID")}
    out = Out(a.out, prov)
    gpu_csv = a.out / "gpu.csv"
    smi_snapshot(a.out / "nvidia-smi-q-before.txt", a.nvml_index)
    parts = a.parts.split(",")
    with GpuSampler(gpu_csv, a.interval, a.nvml_index):
        time.sleep(2 * a.interval)
        if "bandwidth" in parts:
            bandwidth(out, gpu_csv, a.bw_repeats, a.bw_gib)
        if "gemm" in parts:
            gemm_sustained(out, gpu_csv, a.gemm_size, a.sustain_s)
        if "shapes" in parts:
            shapes(out, gpu_csv, [int(x) for x in a.m_list.split(",")], a.shapes.split(","), a.shape_min_s)
        time.sleep(2 * a.interval)
    smi_snapshot(a.out / "nvidia-smi-q-after.txt", a.nvml_index)


if __name__ == "__main__":
    main()
