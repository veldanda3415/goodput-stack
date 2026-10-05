"""Spawn llama-server for one sweep point, wait for /health, sample RSS, stop cleanly."""

from __future__ import annotations

import collections
import gzip
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx

# Lines worth surfacing in the summary (memory accounting printed at load time).
MEMORY_LINE = re.compile(r"(KV buffer size|llama_kv_cache: size|model buffer size|compute buffer size|n_ctx_seq|n_slots|print_info: (n_layer|n_head_kv|n_embd_head_k) )")
MIB = re.compile(r"(\S+) (KV|model|compute) buffer size =\s*([\d.]+) MiB")


def build_args(s: dict) -> list[str]:
    args = [os.path.expanduser(s["binary"])]
    if s.get("model_path"):
        args += ["-m", os.path.expanduser(s["model_path"])]
    else:
        args += ["-hf", s["hf_repo"]]
    args += ["--host", s["host"], "--port", str(s["port"])]
    args += ["-c", str(s["ctx_size"]), "-np", str(s["parallel"]), "-t", str(s["threads"])]
    if s.get("kv_unified") is True:
        args.append("-kvu")
    elif s.get("kv_unified") is False:
        args.append("-no-kvu")
    if s.get("cache_ram_mib") is not None:
        args += ["-cram", str(s["cache_ram_mib"])]
    if s.get("log_verbosity") is not None:
        args += ["-lv", str(s["log_verbosity"])]
    args += [str(a) for a in s.get("extra_args", [])]
    return args


def port_in_use(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


class CappedLog(threading.Thread):
    """Drain the server's stdout so the pipe never blocks; keep head up to a cap + a tail ring."""

    def __init__(self, stream, path: Path, max_bytes: int, tail_lines: int = 2000):
        super().__init__(daemon=True)
        self.stream, self.path, self.max_bytes = stream, path, max_bytes
        self.tail = collections.deque(maxlen=tail_lines)
        self.dropped_bytes = 0
        self.memory_lines: list[str] = []

    def run(self) -> None:
        written = 0
        with open(self.path, "w") as f:
            for raw in self.stream:
                line = raw.decode(errors="replace")
                if MEMORY_LINE.search(line) and len(self.memory_lines) < 50:
                    self.memory_lines.append(line.rstrip())
                if written + len(raw) <= self.max_bytes:
                    f.write(line)
                    written += len(raw)
                else:
                    self.dropped_bytes += len(raw)
                    self.tail.append(line)
            if self.dropped_bytes:
                f.write(f"\n... [harness] truncated {self.dropped_bytes} bytes; last {len(self.tail)} lines follow ...\n")
                f.writelines(self.tail)


class RssSampler(threading.Thread):
    def __init__(self, pid: int, interval: float):
        super().__init__(daemon=True)
        self.pid, self.interval = pid, interval
        self.samples: list[tuple[float, int]] = []  # (unix time, rss KiB)
        self.hwm_kib = 0
        self._halt = threading.Event()

    def _read(self) -> tuple[int, int] | None:
        try:
            status = Path(f"/proc/{self.pid}/status").read_text()
        except OSError:
            return None
        fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        return int(fields["VmRSS"].split()[0]), int(fields["VmHWM"].split()[0])

    def run(self) -> None:
        while not self._halt.is_set():
            got = self._read()
            if got:
                self.samples.append((time.time(), got[0]))
                self.hwm_kib = max(self.hwm_kib, got[1])
            self._halt.wait(self.interval)

    def stop(self) -> None:
        got = self._read()  # final HWM before the process exits
        if got:
            self.hwm_kib = max(self.hwm_kib, got[1])
        self._halt.set()


class LlamaServer:
    def __init__(self, cfg: dict, out_dir: Path, log_name: str = "server.log"):
        self.s = cfg["server"]
        self.cfg = cfg
        self.out_dir = out_dir
        self.log_path = out_dir / log_name
        self.base_url = f"http://{self.s['host']}:{self.s['port']}"
        self.args = build_args(self.s)
        self.proc: subprocess.Popen | None = None
        self.log: CappedLog | None = None
        self.rss: RssSampler | None = None
        self.startup_s: float | None = None
        self.rss_after_load_kib: int | None = None

    def __enter__(self) -> "LlamaServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        if port_in_use(self.s["host"], self.s["port"]):
            raise RuntimeError(f"port {self.s['port']} already in use - stop the other llama-server first")
        t0 = time.monotonic()
        self.proc = subprocess.Popen(
            self.args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        max_bytes = int(self.cfg["storage"]["max_log_mib"] * 1024 * 1024)
        self.log = CappedLog(self.proc.stdout, self.log_path, max_bytes)
        self.log.start()
        self.rss = RssSampler(self.proc.pid, self.cfg["metrics"]["rss_interval_s"])
        self.rss.start()
        self._wait_healthy(t0)
        self.startup_s = time.monotonic() - t0
        if self.rss.samples:
            self.rss_after_load_kib = self.rss.samples[-1][1]

    def _wait_healthy(self, t0: float) -> None:
        deadline = t0 + self.s["startup_timeout_s"]
        with httpx.Client(timeout=2.0) as client:
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"llama-server exited with {self.proc.returncode} during startup; see {self.log_path}")
                try:
                    if client.get(f"{self.base_url}/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.2)
        raise TimeoutError(f"llama-server not healthy after {self.s['startup_timeout_s']}s")

    def stop(self) -> None:
        if self.rss:
            self.rss.stop()
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()
        if self.log:
            self.log.join(timeout=10)
            gzip_file(self.log_path)

    def memory_info(self) -> dict:
        return {
            "startup_s": round(self.startup_s or 0, 3),
            "rss_after_load_mib": round((self.rss_after_load_kib or 0) / 1024, 1),
            "rss_peak_mib": round((self.rss.hwm_kib if self.rss else 0) / 1024, 1),
            "log_memory_lines": self.log.memory_lines if self.log else [],
            "log_truncated_bytes": self.log.dropped_bytes if self.log else 0,
        }


def parse_buffers(lines: list[str]) -> dict:
    """Sum `<backend> <kind> buffer size = X MiB` lines into kv/model/compute MiB."""
    out: dict = {}
    for line in lines:
        m = MIB.search(line)
        if m:
            key = f"{m.group(2).lower()}_buffer_mib"
            out[key] = round(out.get(key, 0) + float(m.group(3)), 2)
    return out


def probe_memory(cfg: dict, out_dir: Path) -> dict:
    """Start the server once at -lv 4 (library INFO lines visible) just to read buffer sizes."""
    probe_cfg = {**cfg, "server": {**cfg["server"], "log_verbosity": 4}}
    with LlamaServer(probe_cfg, out_dir, log_name="probe.log") as srv:
        pass
    return parse_buffers(srv.log.memory_lines) | {"_probe_lines": srv.log.memory_lines}


def gzip_file(path: Path) -> None:
    if not path.exists():
        return
    with open(path, "rb") as src, gzip.open(f"{path}.gz", "wb") as dst:
        shutil.copyfileobj(src, dst)
    path.unlink()
