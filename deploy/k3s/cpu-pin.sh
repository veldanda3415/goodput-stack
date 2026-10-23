#!/usr/bin/env bash
# deploy/k3s/cpu-pin.sh on|off|status — switch the k3s kubelet CPU manager between `static` (exclusive CPUs for
# Guaranteed pods with integer CPU, full physical cores only, cores 0-1 reserved) and the original `none`.
# Run as root via `make cpu-pin-on` / `make cpu-pin-off` (they call sudo, then re-create the pods): it rewrites /etc/rancher/k3s/config.yaml and restarts k3s, which restarts
# the kubelet. Containers keep running across a k3s restart; pods must be re-created to get (or drop) exclusive CPUs.
#
# The state file written under the old policy is removed while k3s is stopped, so the kubelet starts a fresh one for
# the new policy. Root dir = kubelet default /var/lib/kubelet (k3s passes no --root-dir; journal line "Running kubelet").
# Only overwrites the k3s config if it matches one of the two known files in deploy/k3s/ (no blind overwrite).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CFG=/etc/rancher/k3s/config.yaml
STATE=/var/lib/kubelet/cpu_manager_state
ORIG="$HERE/config.yaml"
PINNED="$HERE/config-cpu-pinned.yaml"

status() {
  echo "== $CFG (sha256 $(sha256sum "$CFG" | cut -c1-12))"; cat "$CFG"
  echo "== $STATE"; cat "$STATE" 2>/dev/null || echo "(missing)"; echo
}

switch() {   # $1 = file to install
  [ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 2; }
  cur=$(sha256sum "$CFG" | cut -d' ' -f1)
  case "$cur" in
    "$(sha256sum "$ORIG" | cut -d' ' -f1)"|"$(sha256sum "$PINNED" | cut -d' ' -f1)") ;;
    *) echo "$CFG matches neither $ORIG nor $PINNED; not touching it" >&2; exit 2 ;;
  esac
  cp -p "$CFG" "$CFG.bak-$(date +%Y%m%d-%H%M%S)"
  systemctl stop k3s
  install -m 0644 "$1" "$CFG"
  rm -f "$STATE"
  systemctl start k3s
  for _ in $(seq 1 120); do
    kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get --raw /readyz >/dev/null 2>&1 && break; sleep 1
  done
  kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml wait --for=condition=Ready node --all --timeout=180s
  sleep 2
  status
  journalctl -u k3s --since "-3 min" --no-pager | grep -E 'cpu_manager|CPUManager|policy_static' | tail -8 || true
}

case "${1:-status}" in
  on) switch "$PINNED" ;;
  off) switch "$ORIG" ;;
  status) status ;;
  *) echo "usage: $0 on|off|status" >&2; exit 2 ;;
esac
