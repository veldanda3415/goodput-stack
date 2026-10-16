"""Manage the local exporter and standalone Prometheus used by fabric telemetry."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "fabric" / "telemetry" / ".state"
PID_FILE = STATE_DIR / "exporter.pid"
LOG_FILE = STATE_DIR / "exporter.log"
PROM_CONFIG = ROOT / "fabric" / "telemetry" / "prometheus.yml"
PROM_CONTAINER = "goodput-fabric-prometheus"
PROM_IMAGE = (
    "docker.io/prom/prometheus:v3.8.1"
    "@sha256:2b6f734e372c1b4717008f7d0a0152316aedd4d13ae17ef1e3268dbfaf68041b"
)
PROM_LABEL = "io.goodput.fabric-telemetry"
PROM_METRIC_URL = "http://127.0.0.1:9098/metrics"
EXPORTER_METRIC_URL = "http://127.0.0.1:9109/metrics"


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command)}; "
            f"exit={result.returncode}; stderr={result.stderr.strip()}"
        )
    return result


def process_is_exporter(pid: int) -> bool:
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except FileNotFoundError:
        return False
    return "fabric.telemetry.exporter" in command


def read_exporter_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
    except ValueError as error:
        raise RuntimeError(f"invalid exporter pid file: {PID_FILE}") from error
    if not process_is_exporter(pid):
        PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def exporter_ready(url: str, timeout_seconds: float = 15.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def start_exporter() -> int:
    existing = read_exporter_pid()
    if existing is not None:
        if exporter_ready(EXPORTER_METRIC_URL, timeout_seconds=15):
            return existing
        raise RuntimeError(f"exporter process {existing} is running but not serving metrics")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_FILE.open("ab")
    process = subprocess.Popen(
        [sys.executable, "-m", "fabric.telemetry.exporter"],
        cwd=ROOT,
        env={
            **os.environ,
            "FABRIC_TELEMETRY_ADDRESS": "127.0.0.1",
            "FABRIC_TELEMETRY_PORT": "9109",
        },
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
        close_fds=True,
    )
    log.close()
    PID_FILE.write_text(f"{process.pid}\n", encoding="ascii")
    for _ in range(30):
        if exporter_ready(EXPORTER_METRIC_URL, timeout_seconds=15):
            return process.pid
        if process.poll() is not None:
            raise RuntimeError(
                f"exporter exited with {process.returncode}; inspect {LOG_FILE}"
            )
        time.sleep(1)
    raise RuntimeError(f"exporter did not become ready; inspect {LOG_FILE}")


def prometheus_container() -> dict[str, Any] | None:
    result = run(["podman", "inspect", PROM_CONTAINER], check=False)
    if result.returncode != 0:
        return None
    try:
        container = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError) as error:
        raise RuntimeError(f"could not inspect {PROM_CONTAINER}") from error
    labels = container.get("Config", {}).get("Labels", {})
    if labels.get(PROM_LABEL) != "true":
        raise RuntimeError(
            f"refusing to manage existing container {PROM_CONTAINER} without "
            f"label {PROM_LABEL}=true"
        )
    return container


def up() -> None:
    pid = start_exporter()
    existing = prometheus_container()
    if existing is None:
        run([
            "podman", "run", "-d", "--name", PROM_CONTAINER, "--network", "host",
            "--label", f"{PROM_LABEL}=true",
            "-v", f"{PROM_CONFIG}:/etc/prometheus/prometheus.yml:ro",
            PROM_IMAGE,
            "--config.file=/etc/prometheus/prometheus.yml",
            "--storage.tsdb.path=/prometheus",
            "--web.listen-address=127.0.0.1:9098",
        ])
    elif not existing.get("State", {}).get("Running", False):
        run(["podman", "start", PROM_CONTAINER])
    for _ in range(30):
        if exporter_ready(PROM_METRIC_URL) and exporter_ready(EXPORTER_METRIC_URL):
            print(
                f"Exporter PID {pid} at {EXPORTER_METRIC_URL}; "
                f"Prometheus at {PROM_METRIC_URL}"
            )
            return
        time.sleep(1)
    raise RuntimeError(
        f"telemetry services did not become ready; inspect {LOG_FILE} and "
        f"podman logs {PROM_CONTAINER}"
    )


def down() -> None:
    container = prometheus_container()
    if container is not None:
        if container.get("State", {}).get("Running", False):
            run(["podman", "stop", PROM_CONTAINER])
        run(["podman", "rm", PROM_CONTAINER])
    pid = read_exporter_pid()
    if pid is not None:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not process_is_exporter(pid):
                break
            time.sleep(0.1)
        if process_is_exporter(pid):
            raise RuntimeError(f"exporter PID {pid} did not stop after SIGTERM")
        PID_FILE.unlink(missing_ok=True)
    print("Fabric telemetry services stopped.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "down"))
    args = parser.parse_args()
    if args.action == "up":
        up()
    else:
        down()


if __name__ == "__main__":
    main()
