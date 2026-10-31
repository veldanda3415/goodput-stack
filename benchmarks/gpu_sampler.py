"""Sample one GPU with NVML (pynvml from nvidia-ml-py) and `nvidia-smi --query-gpu` at a fixed interval and write CSV.

    python benchmarks/gpu_sampler.py --out gpu.csv                 # until Ctrl-C / SIGTERM, 2 Hz
    python benchmarks/gpu_sampler.py --out gpu.csv --duration 60 --interval 1 --index 0
    python benchmarks/gpu_sampler.py --list-fields                 # what this nvidia-smi offers, what is sampled

    from benchmarks.gpu_sampler import GpuSampler
    with GpuSampler("gpu.csv"):                                    # background thread, 2 Hz
        run_load()

NVML columns (unchanged from the first version): t_unix, t_rel_s, gpu, util_gpu_pct, util_mem_pct, mem_used_mib,
mem_total_mib, power_w, sm_clock_mhz, temp_c (+ error, if a read failed).

nvidia-smi columns (named exactly as the field, e.g. `clocks.sm`, `clocks_throttle_reasons.sw_power_cap`): SMI_WANTED
plus every clock-throttle / clock-event reason field. The names are not assumed: `nvidia-smi --help-query-gpu` is
parsed once per process and only fields it lists are queried (newer drivers list `clocks_event_reasons.X` with
`clocks_throttle_reasons.X` as an alias on the same line; the throttle name is used when listed). Values come from one
long-running `nvidia-smi --query-gpu=... --format=csv,noheader,nounits -lms <interval>` process; each CSV row carries
the latest line it printed and its age (`smi_age_s`). Reason fields are written as 1 (Active) / 0 (Not Active);
`clocks_throttle_reasons.active` / `.supported` stay hex bitmasks. A sidecar `<out>.fields.json` records the command,
the fields chosen, the aliases and the wanted fields this nvidia-smi does not list.

What util_gpu_pct is NOT: NVML's "GPU utilization" is the percent of the sample period during which
at least one kernel was running on the GPU. One tiny kernel on one SM reads 100 %. It says nothing about
how many SMs were busy or how well they were used (that is DCGM's SM_ACTIVE / SM_OCCUPANCY, profiling
metrics that need the DCGM host engine). util_mem_pct is likewise "percent of time memory was being read
or written", not bandwidth used. Treat both as busy/idle signals.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

FIELDS = ["t_unix", "t_rel_s", "gpu", "util_gpu_pct", "util_mem_pct", "mem_used_mib", "mem_total_mib",
          "power_w", "sm_clock_mhz", "temp_c", "error"]
SMI_WANTED = ["clocks.sm", "clocks.mem", "clocks.max.sm", "clocks.applications.graphics", "power.draw",
              "power.draw.instant", "power.draw.average", "power.limit", "enforced.power.limit", "power.default_limit",
              "power.min_limit", "power.max_limit", "temperature.gpu", "pstate"]
SMI_OPTIONAL = {"power.draw.instant", "power.draw.average"}   # newer drivers only; not "missing" when absent
REASON_PREFIXES = ("clocks_throttle_reasons.", "clocks_event_reasons.")
REASON_MASKS = ("active", "supported")   # hex bitmasks, not Active / Not Active


# ---------------------------------------------------------------- nvidia-smi field discovery + parsing (pure, unit-tested)

def parse_help_query_gpu(text: str) -> list[list[str]]:
    """`nvidia-smi --help-query-gpu` -> one list of names per property; a property line names the field and its
    aliases in quotes ("clocks_event_reasons.active" or "clocks_throttle_reasons.active")."""
    groups = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('"') and re.fullmatch(r'"[^"\s]+"(\s+or\s+"[^"\s]+")*', s):
            groups.append(re.findall(r'"([^"]+)"', s))
    return groups


def reason_suffix(name: str) -> str | None:
    for p in REASON_PREFIXES:
        if name.startswith(p):
            return name[len(p):]
    return None


def select_fields(groups: list[list[str]], wanted: list[str] = SMI_WANTED) -> dict:
    """Fields to query: each wanted field that a group lists (under its own name), then every throttle / event
    reason (throttle-name preferred). Returns {fields, aliases, missing}."""
    listed = {n: g for g in groups for n in g}
    fields, aliases, missing = [], {}, []
    for w in wanted:
        if w in listed:
            fields.append(w)
            others = [n for n in listed[w] if n != w]
            if others:
                aliases[w] = others
        elif w not in SMI_OPTIONAL:
            missing.append(w)
    seen = set()
    for g in groups:
        sufs = {reason_suffix(n) for n in g} - {None}
        if not sufs:
            continue
        suf = sorted(sufs)[0]
        if suf in seen:
            continue
        seen.add(suf)
        pick = next((n for n in g if n.startswith("clocks_throttle_reasons.")), g[0])
        fields.append(pick)
        if len(g) > 1:
            aliases[pick] = [n for n in g if n != pick]
    for w in ("clocks_throttle_reasons.active", "clocks_throttle_reasons.gpu_idle",
              "clocks_throttle_reasons.applications_clocks_setting", "clocks_throttle_reasons.sw_power_cap",
              "clocks_throttle_reasons.hw_slowdown", "clocks_throttle_reasons.hw_thermal_slowdown",
              "clocks_throttle_reasons.hw_power_brake_slowdown", "clocks_throttle_reasons.sw_thermal_slowdown"):
        if not any(reason_suffix(f) == reason_suffix(w) for f in fields):
            missing.append(w)
    return {"fields": fields, "aliases": aliases, "missing": missing}


def parse_value(field: str, raw: str):
    """One `--format=csv,nounits` value -> int/float, 1/0 for Active/Not Active, '' for N/A, else the string."""
    s = raw.strip()
    if s in ("", "[N/A]", "N/A", "[Not Supported]", "Not Supported", "[Unknown Error]", "[Insufficient Permissions]"):
        return ""
    if s == "Active":
        return 1
    if s == "Not Active":
        return 0
    if s.lower().startswith("0x"):
        return s   # bitmask: keep exact
    try:
        f = float(s)
        return int(f) if f.is_integer() and "." not in s else f
    except ValueError:
        return s


def parse_smi_line(fields: list[str], line: str) -> dict:
    vals = next(csv.reader([line], skipinitialspace=True), [])
    if len(vals) != len(fields):
        return {"smi_error": f"{len(vals)} values for {len(fields)} fields: {line.strip()[:200]}"}
    return {f: parse_value(f, v) for f, v in zip(fields, vals)}


# ---------------------------------------------------------------- runtime

_FIELD_CACHE: dict | None = None


def smi_fields() -> dict:
    """Discover the fields once per process (`nvidia-smi --help-query-gpu`)."""
    global _FIELD_CACHE
    if _FIELD_CACHE is None:
        try:
            r = subprocess.run(["nvidia-smi", "--help-query-gpu"], capture_output=True, text=True, timeout=60)
            _FIELD_CACHE = {"help_rc": r.returncode, **select_fields(parse_help_query_gpu(r.stdout))}
        except (OSError, subprocess.TimeoutExpired) as exc:
            _FIELD_CACHE = {"help_rc": None, "help_error": repr(exc), "fields": [], "aliases": {}, "missing": SMI_WANTED}
    return _FIELD_CACHE


def smi_snapshot(path: str | Path, index: int | None = None, sections: str = "PERFORMANCE,POWER,CLOCK,TEMPERATURE") -> int:
    """`nvidia-smi -q -d <sections> [-i index]` saved to `path` (before / after every load run). Returns rc."""
    cmd = ["nvidia-smi", "-q", "-d", sections] + (["-i", str(index)] if index is not None else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        rc, text = r.returncode, r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        rc, text = 127, repr(exc)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(f"$ {' '.join(cmd)}\n# rc={rc} t_unix={time.time():.3f}\n{text}")
    return rc


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


class _SmiStream:
    """One `nvidia-smi --query-gpu ... -lms N` process; keeps the latest parsed line."""

    def __init__(self, fields: list[str], index: int, interval_s: float):
        self.fields = fields
        self.cmd = ["nvidia-smi", f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits", "-i", str(index),
                    "-lms", str(max(100, int(interval_s * 1000)))]
        self.latest: dict = {}
        self.t_latest: float | None = None
        self.error: str | None = None
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        try:
            self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except OSError as exc:
            self.error = repr(exc)
            return
        threading.Thread(target=self._read, name="gpu-sampler-smi", daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            row = parse_smi_line(self.fields, line)
            if "smi_error" in row:
                self.error = row["smi_error"]
                continue
            self.latest, self.t_latest = row, time.monotonic()
        rc = self.proc.wait()
        if rc:
            self.error = f"nvidia-smi -lms exited rc={rc}" + (f"; last: {self.error}" if self.error else "")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class GpuSampler:
    """Background NVML + nvidia-smi sampler; a context manager. Writes and flushes one CSV row per sample."""

    def __init__(self, out: str | Path, interval_s: float = 0.5, index: int = 0, smi: bool = True):
        self.out, self.interval_s, self.index, self.smi = Path(out), interval_s, index, smi
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: _SmiStream | None = None
        self.rows = 0

    def _loop(self) -> None:
        import pynvml as nv
        nv.nvmlInit()
        try:
            handle = nv.nvmlDeviceGetHandleByIndex(self.index)
            smi_cols = self._stream.fields if self._stream else []
            extra = (["smi_age_s", "smi_error"] if self._stream else [])
            t0 = time.monotonic()
            with open(self.out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS + smi_cols + extra)
                w.writeheader()
                nxt = t0
                while not self._stop.is_set():
                    now = time.monotonic()
                    row = {"t_unix": round(time.time(), 3), "t_rel_s": round(now - t0, 3), "gpu": self.index}
                    try:
                        row |= read(nv, handle)
                    except nv.NVMLError as exc:
                        row["error"] = str(exc)
                    if self._stream:
                        row |= self._stream.latest
                        row["smi_age_s"] = round(now - self._stream.t_latest, 3) if self._stream.t_latest else ""
                        row["smi_error"] = self._stream.error or ""
                    w.writerow(row)
                    f.flush()
                    self.rows += 1
                    nxt += self.interval_s
                    self._stop.wait(max(0.0, nxt - time.monotonic()))
        finally:
            nv.nvmlShutdown()

    def start(self) -> "GpuSampler":
        self.out.parent.mkdir(parents=True, exist_ok=True)
        if self.smi:
            info = smi_fields()
            if info["fields"]:
                self._stream = _SmiStream(info["fields"], self.index, self.interval_s)
                self._stream.start()
            self.out.with_suffix(self.out.suffix + ".fields.json").write_text(json.dumps(
                {**info, "cmd": self._stream.cmd if self._stream else None, "interval_s": self.interval_s,
                 "field_source": "nvidia-smi --help-query-gpu (parsed in-session)"}, indent=2) + "\n")
        self._thread = threading.Thread(target=self._loop, name="gpu-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._stream:
            self._stream.stop()

    def __enter__(self) -> "GpuSampler":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


NUMERIC = ("util_gpu_pct", "util_mem_pct", "mem_used_mib", "power_w", "sm_clock_mhz", "temp_c",
           "clocks.sm", "clocks.mem", "clocks.max.sm", "clocks.applications.graphics", "power.draw", "power.draw.instant",
           "power.draw.average", "power.limit", "enforced.power.limit", "power.default_limit", "power.min_limit",
           "power.max_limit", "temperature.gpu")


def summarize_rows(rows: list[dict], prefix: str = "gpu_") -> dict:
    """Mean/max of numeric columns, fraction of samples with each throttle / event reason Active, pstate counts."""
    out: dict = {f"{prefix}samples": len(rows)}
    for col in NUMERIC:
        vals = []
        for r in rows:
            try:
                vals.append(float(r[col]))
            except (KeyError, TypeError, ValueError):
                pass
        if vals:
            key = col.replace(".", "_")
            out[f"{prefix}{key}_mean"] = round(sum(vals) / len(vals), 2)
            out[f"{prefix}{key}_max"] = max(vals)
            out[f"{prefix}{key}_min"] = min(vals)
    for col in sorted({c for r in rows for c in r if reason_suffix(c) and reason_suffix(c) not in REASON_MASKS}):
        vals = [r[col] for r in rows if str(r.get(col, "")) in ("0", "1")]
        if vals:
            out[f"{prefix}reason_{reason_suffix(col)}_frac"] = round(sum(int(v) for v in vals) / len(vals), 4)
    masks = [r.get("clocks_throttle_reasons.active") or r.get("clocks_event_reasons.active") for r in rows]
    masks = [m for m in masks if m]
    if masks:
        out[f"{prefix}reason_active_masks"] = {m: masks.count(m) for m in sorted(set(masks))}
    ps = [r.get("pstate") for r in rows if r.get("pstate")]
    if ps:
        out[f"{prefix}pstate_counts"] = {p: ps.count(p) for p in sorted(set(ps))}
    return out


def load_rows(path: str | Path, t0: float | None = None, t1: float | None = None) -> list[dict]:
    with open(path) as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error")]
    if t0 is not None:
        rows = [r for r in rows if t0 <= float(r["t_unix"]) <= (t1 if t1 is not None else float("inf"))]
    return rows


def summarize(path: str | Path, t0: float | None = None, t1: float | None = None, prefix: str = "gpu_") -> dict:
    """Summary of one sampler CSV, optionally only rows with t0 <= t_unix <= t1 (for result rows)."""
    return summarize_rows(load_rows(path, t0, t1), prefix)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="CSV path")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between samples (default 0.5 = 2 Hz)")
    ap.add_argument("--index", type=int, default=0, help="NVML / nvidia-smi device index")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = until SIGINT/SIGTERM)")
    ap.add_argument("--no-smi", action="store_true", help="NVML columns only")
    ap.add_argument("--list-fields", action="store_true", help="print the nvidia-smi fields that would be sampled")
    a = ap.parse_args()
    if a.list_fields:
        print(json.dumps(smi_fields(), indent=2))
        return
    if not a.out:
        ap.error("--out is required")
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    s = GpuSampler(a.out, a.interval, a.index, smi=not a.no_smi).start()
    try:
        done.wait(a.duration or None)
    except KeyboardInterrupt:
        pass
    s.stop()
    print(f"{s.rows} samples -> {a.out}")


if __name__ == "__main__":
    main()
