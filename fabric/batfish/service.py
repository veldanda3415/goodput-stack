"""Start/stop the pinned local Batfish container (rootless Podman, loopback only).

Image: batfish/allinone 2026.08.27.3685, pinned by digest (the only non-test
release tag published on Docker Hub when F5 ran; also `latest`).
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import time

IMAGE = (
    "docker.io/batfish/allinone:2026.08.27.3685@sha256:"
    "54cb0ed94fd9a3c1ca0985f73e5be479e955cee9b9f6a6799b66be3364fd8e5c"
)
NAME = "goodput-batfish"
PORT = 9996


def running() -> bool:
    out = subprocess.run(["podman", "ps", "--filter", f"name=^{NAME}$", "--format", "{{.Names}}"],
                         capture_output=True, text=True, check=False)
    return NAME in out.stdout.split()


def wait_ready(timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=2):
                pass
            from pybatfish.client.session import Session
            Session(host="127.0.0.1").list_networks()
            return
        except Exception:  # noqa: BLE001 - service still starting
            time.sleep(2)
    raise RuntimeError(f"Batfish did not answer on 127.0.0.1:{PORT} within {timeout}s")


def up() -> None:
    if not running():
        subprocess.run(["podman", "rm", "-f", NAME], capture_output=True, check=False)
        subprocess.run([
            "podman", "run", "-d", "--name", NAME,
            "-p", f"127.0.0.1:{PORT}:9996", "-p", "127.0.0.1:9997:9997",
            IMAGE,
        ], check=True)
    wait_ready()
    print(f"Batfish ready on 127.0.0.1:{PORT} ({IMAGE})")


def down() -> None:
    subprocess.run(["podman", "rm", "-f", NAME], capture_output=True, check=False)
    print(f"stopped {NAME}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up", "down"])
    args = parser.parse_args()
    up() if args.command == "up" else down()
