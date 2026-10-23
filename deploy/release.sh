#!/usr/bin/env bash
# deploy/release.sh — the upgrade flow for the inference chart: lint -> diff -> confirm -> upgrade -> test.
#
#   deploy/release.sh all  [k3s|k3d]     # the whole flow; asks before upgrading (--yes to skip)
#   deploy/release.sh lint [env]          # helm lint with the env's values
#   deploy/release.sh diff [env]          # what an upgrade would change on the live cluster
#   deploy/release.sh upgrade [env]       # helm upgrade --install, waits, rolls back on failure
#   deploy/release.sh test [env]          # helm test (sanity pods for llama.cpp + simulator)
#   make deploy ENV=k3s  /  make deploy-diff ENV=k3d  ...
#
# Values: values.yaml (shared) + values-<env>.yaml (per cluster), always both.
# Every kubectl/helm call names the env's kube context explicitly, so k3d values can never be
# applied to the k3s cluster just because it happens to be the current context.
#
# Diff: uses the helm-diff plugin if installed (`helm plugin install https://github.com/databus23/helm-diff`),
# otherwise `helm template | kubectl diff --server-side` as field manager "helm" (what Helm 4's
# server-side apply would do) plus a list of objects the upgrade would DELETE, which kubectl diff
# cannot show. Exit codes: 0 ok (diff: no changes) · 1 diff found changes · 2+ error / aborted.
set -euo pipefail

ACTION=${1:-all}
ENV=${2:-${ENV:-k3s}}
YES=0
for a in "$@"; do [ "$a" = --yes ] || [ "$a" = -y ] && YES=1; done

RELEASE=${RELEASE:-inf}
NS=${NS:-inference}
HERE=$(cd "$(dirname "$0")" && pwd)
CHART="$HERE/charts/inference"
case "$ENV" in
  k3s) CTX=${KUBE_CONTEXT:-default} ;;
  k3d) CTX=${KUBE_CONTEXT:-k3d-goodput} ;;
  *) echo "unknown env '$ENV' (k3s|k3d)" >&2; exit 2 ;;
esac
VALUES=(-f "$CHART/values.yaml" -f "$CHART/values-$ENV.yaml")
# OVERLAYS="values-k3s-p8cpu.yaml values-k3s-pinned.yaml": experiment overlays on top, in order (chart-relative).
for o in ${OVERLAYS:-}; do VALUES+=(-f "$CHART/$o"); done
HELM=(helm --kube-context "$CTX" -n "$NS")
KUBECTL=(kubectl --context "$CTX" -n "$NS")

say() { printf '\n== %s\n' "$*"; }

preflight() {
  kubectl config get-contexts "$CTX" >/dev/null 2>&1 || { echo "kube context '$CTX' not found (env $ENV)" >&2; exit 2; }
  kubectl --context "$CTX" get --raw /readyz >/dev/null 2>&1 || { echo "cluster '$CTX' not reachable" >&2; exit 2; }
}

lint() {
  say "lint ($ENV)"
  helm lint "$CHART" "${VALUES[@]}"
}

deleted_objects() {  # objects in the live release that the new render no longer contains
  "${HELM[@]}" get manifest "$RELEASE" 2>/dev/null > "$1.old" || return 0
  python3 - "$1.old" "$1" <<'PY'
import sys, yaml
def ids(path):
    out = set()
    for d in yaml.safe_load_all(open(path)):
        if d and d.get("kind"):
            out.add((d["kind"], d["metadata"]["name"]))
    return out
gone = sorted(ids(sys.argv[1]) - ids(sys.argv[2]))
for kind, name in gone:
    print(f"WOULD DELETE  {kind}/{name}")
sys.exit(1 if gone else 0)
PY
}

diff_() {
  say "diff ($ENV, context $CTX): live cluster -> this checkout"
  if helm plugin list 2>/dev/null | awk '{print $1}' | grep -qx diff; then
    "${HELM[@]}" diff upgrade "$RELEASE" "$CHART" "${VALUES[@]}" --allow-unreleased --detailed-exitcode
    return
  fi
  local tmp rc=0 gone=0
  tmp=$(mktemp)
  helm template "$RELEASE" "$CHART" -n "$NS" "${VALUES[@]}" --skip-tests |
    python3 -c '
import sys, yaml
# Helm stamps these ownership annotations on every object at install/upgrade; `helm template`
# leaves them out, so without them every object would show a bogus "annotation removed" diff.
rel, ns = sys.argv[1], sys.argv[2]
docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
for d in docs:
    d["metadata"].setdefault("annotations", {}).update(
        {"meta.helm.sh/release-name": rel, "meta.helm.sh/release-namespace": ns})
yaml.safe_dump_all(docs, sys.stdout, sort_keys=False)' "$RELEASE" "$NS" > "$tmp"
  deleted_objects "$tmp" || gone=1
  "${KUBECTL[@]}" diff --server-side --field-manager=helm --force-conflicts -f "$tmp" || rc=$?
  rm -f "$tmp" "$tmp.old"
  [ $rc -gt 1 ] && { echo "kubectl diff failed (rc $rc)" >&2; return $rc; }
  if [ $rc = 0 ] && [ $gone = 0 ]; then echo "no changes"; return 0; fi
  return 1
}

upgrade() {
  say "upgrade ($ENV, context $CTX)"
  "${HELM[@]}" upgrade --install "$RELEASE" "$CHART" --create-namespace "${VALUES[@]}" \
    --wait --timeout 5m --rollback-on-failure
  "${HELM[@]}" history "$RELEASE" --max 3
}

test_() {
  say "helm test ($ENV)"
  "${HELM[@]}" test "$RELEASE" --logs
}

[ "$ACTION" = lint ] || preflight   # lint renders offline; everything else talks to the cluster
case "$ACTION" in
  lint) lint ;;
  diff) diff_ ;;
  upgrade) upgrade ;;
  test) test_ ;;
  all)
    lint
    rc=0; diff_ || rc=$?
    [ $rc -gt 1 ] && exit $rc
    if [ $rc = 0 ]; then echo "(no changes: upgrading anyway records a new revision with the same manifests)"; fi
    if [ $YES != 1 ]; then
      read -r -p "upgrade release '$RELEASE' in $CTX/$NS? [y/N] " a
      [ "$a" = y ] || [ "$a" = Y ] || { echo "aborted"; exit 2; }
    fi
    upgrade
    test_
    ;;
  *) echo "unknown action '$ACTION' (all|lint|diff|upgrade|test)" >&2; exit 2 ;;
esac
