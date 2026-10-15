"""Sample one GPU with NVML (pynvml from nvidia-ml-py) at a fixed interval and write CSV.

    python benchmarks/gpu_sampler.py --out gpu.csv                 # until Ctrl-C / SIGTERM
    python benchmarks/gpu_sampler.py --out gpu.csv --duration 60 --interval 1 --index 0

    from benchmarks.gpu_sampler import GpuSampler
    with GpuSampler("gpu.csv"):                                    # background thread, 1 Hz
        run_load()

Columns: t_unix, t_rel_s, gpu, util_gpu_pct, util_mem_pct, mem_used_mib, mem_total_mib, power_w,
sm_clock_mhz, temp_c (+ error, if a read failed).

What util_gpu_pct is NOT: NVML's "GPU utilization" is the percent of the sample period during which
at least one kernel was running on the GPU. One tiny kernel on one SM reads 100 %. It says nothing about
how many SMs were busy or how well they were used (that is DCGM's SM_ACTIVE / SM_OCCUPANCY, profiling
metrics that need the DCGM host engine). util_mem_pct is likewise "percent of time memory was being read
or written", not bandwidth used. Treat both as busy/idle signals.
"""

from __future__ import annotations

import argparse
import csv
import signal
import threading
import time
from pathlib import Path

FIELDS = ["t_unix", "t_rel_s", "gpu", "util_gpu_pct", "util_mem_pct", "mem_used_mib", "mem_total_mib",
          "power_w", "sm_clock_mhz", "temp_c", "error"]


def read(nv, handle) -> dict:
    util = nv.nvmlDeviceGetUtilizationRates(handle)
    mem = nv.nvmlDeviceGetMemoryInfo(handle)
    return {
        "util_gpu_pct": util.gpu,
        "util_mem_pct": util.memory,
        "mem_used_mib": round(mem.used / 2**20, 1),
        "mem_total_mib": round(mem.total / 2**20, 1),
        "power_w": round(nv.nvmlDeviceGetPowerUsage(handle) / 1000, 2),
        "sm_clock_mhz": nv.nvmlDeviceGetClockInfo(handle, nv.NVML_CLOCK_SM),
        "temp_c": nv.nvmlDeviceGetTemperature(handle, nv.NVML_TEMPERATURE_GPU),
    }


class GpuSampler:
    """Background NVML sampler; a context manager. Writes and flushes one CSV row per sample."""

    def __init__(self, out: str | Path, interval_s: float = 1.0, index: int = 0):
        self.out, self.interval_s, self.index = Path(out), interval_s, index
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.rows = 0

    def _loop(self) -> None:
        import pynvml as nv
        nv.nvmlInit()
        try:
            handle = nv.nvmlDeviceGetHandleByIndex(self.index)
            t0 = time.monotonic()
            with open(self.out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                nxt = t0
                while not self._stop.is_set():
                    row = {"t_unix": round(time.time(), 3), "t_rel_s": round(time.monotonic() - t0, 3), "gpu": self.index}
                    try:
                        row |= read(nv, handle)
                    except nv.NVMLError as exc:
                        row["error"] = str(exc)
                    w.writerow(row)
                    f.flush()
                    self.rows += 1
                    nxt += self.interval_s
                    self._stop.wait(max(0.0, nxt - time.monotonic()))
        finally:
            nv.nvmlShutdown()

    def start(self) -> "GpuSampler":
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._loop, name="gpu-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self) -> "GpuSampler":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def summarize(path: str | Path) -> dict:
    """Mean/max of the numeric columns of one sampler CSV (for result rows)."""
    with open(path) as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error")]
    out: dict = {"gpu_samples": len(rows)}
    for col in ("util_gpu_pct", "util_mem_pct", "mem_used_mib", "power_w", "sm_clock_mhz", "temp_c"):
        vals = [float(r[col]) for r in rows if r.get(col) not in (None, "")]
        if vals:
            out[f"gpu_{col}_mean"] = round(sum(vals) / len(vals), 2)
            out[f"gpu_{col}_max"] = max(vals)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="CSV path")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between samples (default 1)")
    ap.add_argument("--index", type=int, default=0, help="NVML device index")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = until SIGINT/SIGTERM)")
    a = ap.parse_args()
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    s = GpuSampler(a.out, a.interval, a.index).start()
    try:
        done.wait(a.duration or None)
    except KeyboardInterrupt:
        pass
    s.stop()
    print(f"{s.rows} samples -> {a.out}")


if __name__ == "__main__":
    main()
