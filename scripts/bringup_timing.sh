#!/usr/bin/env bash
# scripts/bringup_timing.sh — how long until a new backend pod is actually serving?
#
# Measures the bring-up timeline of one of the inference chart's backends (llama.cpp by default,
# or the vLLM simulator with --backend sim), from a trigger to the Service answering, for warm
# and cold starts. Run it on demand after a chart change (do your `helm upgrade` first; this
# script only measures).
#
#   scripts/bringup_timing.sh --backend sim                # simulator: no model, so this is the
#                                                          # pure k8s + probe overhead baseline
#   scripts/bringup_timing.sh                              # warm, rollout restart, 3 runs
#   scripts/bringup_timing.sh --trigger delete             # warm, pod delete -> measures the outage
#   scripts/bringup_timing.sh --trigger scale              # warm scale-from-zero
#   sudo -v && scripts/bringup_timing.sh --mode cold-cache # page cache evicted (needs sudo)
#   scripts/bringup_timing.sh --mode cold-model --yes      # model deleted -> re-download (~470 MB)
#
# Modes (what is NOT cached when the new pod starts):
#   warm        everything cached: image, model on PVC, model in page cache
#   cold-cache  model file evicted from the OS page cache  -> load reads from disk   (trigger: scale)
#   cold-model  model file deleted from the PVC (by a helper pod, after scale-to-0; the server
#               mounts /models read-only) -> init re-downloads it. No sudo needed. Note: the
#               freshly written file stays in the page cache, so the LOAD itself is warm;
#               combine with cold-cache semantics only on a real new node              (trigger: scale)
# Triggers:
#   restart     kubectl rollout restart; old pod serves until the new one is Ready (expect 0 errors)
#   delete      delete the pod; the ReplicaSet replaces it (measures downtime)
#   scale       scale to 0, wait until no pod is left, [cold prep], scale back up (scale-from-zero)
#   Cold modes force `scale`: llama.cpp mmaps the model, and pages mapped by a running
#   process can't be evicted, so the old pod must be gone before the cache is dropped.
#
# Backends: llamacpp (port 8080, /health, model load from the llama-server log) and sim (port 8000,
#   /health/ready, warm only; "model load" = process start -> HTTP listening, from the container
#   runtime's log timestamps; with sim.config.startup-duration set, Ready waits that long more).
#
# Timeline sources: Kubernetes timestamps (whole seconds, rounded DOWN, so they can read up to
# 1 s before the trigger), the script's own polling of pod/EndpointSlice state (~0.5 s),
# llama-server's log (ms, relative to process start), and a prober pod hitting the Service
# every ~0.1 s (timestamped on this host on arrival).
#
# Exit codes: 0 all runs ok · 1 a run failed or timed out (diagnostics saved) · 2 usage/preflight.
set -uo pipefail

MODE=warm TRIGGER="" RUNS="" NS=inference RELEASE=inf TIMEOUT=300 YES=0 KEEP_PROBER=0 BACKEND=llamacpp
OUT_ROOT=benchmarks/results/bringup
PROBER_IMAGE=curlimages/curl:8.10.1

usage() { sed -n '2,/^set -uo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit "${1:-0}"; }
die() { echo "error: $*" >&2; exit 2; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
now() { date +%s.%N; }

while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE=$2; shift 2 ;;
    --backend) BACKEND=$2; shift 2 ;;
    --trigger) TRIGGER=$2; shift 2 ;;
    --runs) RUNS=$2; shift 2 ;;
    --namespace|-n) NS=$2; shift 2 ;;
    --release) RELEASE=$2; shift 2 ;;
    --timeout) TIMEOUT=$2; shift 2 ;;
    --out) OUT_ROOT=$2; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --keep-prober) KEEP_PROBER=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 2 ;;
  esac
done

case "$MODE" in warm|cold-cache|cold-model) ;; *) die "--mode must be warm|cold-cache|cold-model" ;; esac
case "$BACKEND" in
  llamacpp) NAME=llamacpp PORT=8080 HEALTH=/health CONTAINER=llama-server ;;
  sim)      NAME=vllm-sim PORT=8000 HEALTH=/health/ready CONTAINER=vllm-sim
            [ "$MODE" = warm ] || die "--backend sim has no model to make cold: use --mode warm" ;;
  *) die "--backend must be llamacpp|sim" ;;
esac
if [ "$MODE" = warm ]; then
  TRIGGER=${TRIGGER:-restart}; RUNS=${RUNS:-3}
else
  [ -n "$TRIGGER" ] && [ "$TRIGGER" != scale ] && die "$MODE needs --trigger scale (mapped model pages can't be evicted while the old pod runs)"
  TRIGGER=scale; RUNS=${RUNS:-1}
fi
case "$TRIGGER" in restart|delete|scale) ;; *) die "--trigger must be restart|delete|scale" ;; esac
[[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"

DEPLOY="${RELEASE}-${NAME}"
SVC="${RELEASE}-${NAME}"
SEL="app.kubernetes.io/name=${NAME},app.kubernetes.io/instance=${RELEASE}"
PROBER="bringup-prober-$$"
K="kubectl -n $NS"

# ---------------------------------------------------------------- preflight
for t in kubectl curl python3 helm; do command -v $t >/dev/null || die "$t not found"; done
kubectl get ns "$NS" >/dev/null 2>&1 || die "namespace $NS not found (context: $(kubectl config current-context))"
$K get deploy "$DEPLOY" >/dev/null 2>&1 || die "deployment $DEPLOY not found in $NS"
$K rollout status deploy/"$DEPLOY" --timeout=5s >/dev/null 2>&1 || die "deployment $DEPLOY is not fully rolled out; fix that first"
REPLICAS=$($K get deploy "$DEPLOY" -o jsonpath='{.spec.replicas}')
[ "$REPLICAS" = 1 ] || die "expects 1 replica (found $REPLICAS); the timeline follows a single new pod"
MODEL_PATH=$($K get deploy "$DEPLOY" -o jsonpath='{.spec.template.spec.containers[0].args}' |
  python3 -c 'import json,sys; a=json.load(sys.stdin); print(a[a.index("-m")+1] if "-m" in a else "none (simulator)")')
MODEL_PVC=$($K get deploy "$DEPLOY" -o jsonpath='{.spec.template.spec.volumes[?(@.name=="models")].persistentVolumeClaim.claimName}')
if [ "$MODE" = cold-model ] && [ -z "$MODEL_PVC" ]; then
  die "cold-model needs the model on a PVC (model.source: pvc); this deployment has none"
fi
if [ "$MODE" = cold-cache ]; then
  sudo -n true 2>/dev/null || die "cold-cache drops the page cache and needs sudo: run 'sudo -v' first, then re-run"
fi
if [ "$MODE" = cold-model ] && [ "$YES" != 1 ]; then
  read -r -p "cold-model deletes $MODEL_PATH from the PVC and re-downloads it (~470 MB) each run. Continue? [y/N] " a
  [ "$a" = y ] || [ "$a" = Y ] || { echo "aborted"; exit 2; }
fi

RUN_ROOT="$OUT_ROOT/$(date +%Y%m%d-%H%M%S)_${MODE}_${TRIGGER}$([ "$BACKEND" = llamacpp ] || echo "_$BACKEND")"
mkdir -p "$RUN_ROOT"
log "backend=$BACKEND mode=$MODE trigger=$TRIGGER runs=$RUNS -> $RUN_ROOT"

# provenance (once per series)
{
  printf '{"backend":"%s","git_commit":"%s",' "$BACKEND" "$(git rev-parse --short HEAD 2>/dev/null)"
  printf '"git_dirty":%s,' "$([ -n "$(git status --porcelain deploy 2>/dev/null)" ] && echo true || echo false)"
  printf '"helm":%s,' "$(helm list -n "$NS" -f "^${RELEASE}\$" -o json | python3 -c 'import json,sys; r=json.load(sys.stdin); r=r[0] if r else {}; print(json.dumps({k:r.get(k) for k in ("chart","revision","app_version","updated")}))')"
  printf '"values_sha256":"%s",' "$(helm get values "$RELEASE" -n "$NS" -a -o json | sha256sum | cut -c1-12)"
  printf '"image":"%s",' "$($K get deploy "$DEPLOY" -o jsonpath='{.spec.template.spec.containers[0].image}')"
  printf '"model_path":"%s","context":"%s","node":"%s"}\n' "$MODEL_PATH" "$(kubectl config current-context)" \
    "$($K get pod -l "$SEL" -o jsonpath='{.items[0].spec.nodeName}')"
} > "$RUN_ROOT/provenance.json"

# ---------------------------------------------------------------- prober
# A curl pod labelled sanity-test (allowed by the NetworkPolicy), created BEFORE the trigger so
# kube-router has admitted it. The loop runs via `kubectl exec`; this host timestamps each line.
PROBE_PID=""
start_prober() {
  $K run "$PROBER" --restart=Never --image="$PROBER_IMAGE" \
    --labels="app.kubernetes.io/component=sanity-test,app.kubernetes.io/part-of=goodput-stack" \
    --command -- sleep 86400 >/dev/null || die "could not create prober pod"
  $K wait --for=condition=Ready pod/"$PROBER" --timeout=60s >/dev/null || die "prober pod not ready"
  local i=0
  until $K exec "$PROBER" -- curl -s -o /dev/null -m 1 -w '%{http_code}' "http://$SVC:$PORT$HEALTH" 2>/dev/null | grep -q 200; do
    i=$((i+1)); [ $i -ge 30 ] && die "prober can't reach http://$SVC:$PORT$HEALTH (NetworkPolicy allows sanity-test?)"
    sleep 1
  done
}
probe_start() {  # $1 = output file
  ( $K exec "$PROBER" -- sh -c "while true; do curl -s -o /dev/null -m 1 -w '%{http_code}\n' http://$SVC:$PORT$HEALTH; sleep 0.1; done" 2>/dev/null |
      while IFS= read -r code; do printf '%s %s\n' "$(date +%s.%N)" "$code"; done > "$1" ) &
  PROBE_PID=$!
}
probe_stop() {
  [ -n "$PROBE_PID" ] && { pkill -P "$PROBE_PID" 2>/dev/null; kill "$PROBE_PID" 2>/dev/null; wait "$PROBE_PID" 2>/dev/null; }
  PROBE_PID=""
}
cleanup() {
  probe_stop
  if [ "$KEEP_PROBER" = 1 ]; then echo "prober kept: $K delete pod $PROBER"
  else $K delete pod "$PROBER" --now --ignore-not-found >/dev/null 2>&1; fi
  # never leave the deployment scaled to zero
  if [ "$($K get deploy "$DEPLOY" -o jsonpath='{.spec.replicas}' 2>/dev/null)" = 0 ]; then
    echo "restoring $DEPLOY to 1 replica"; $K scale deploy/"$DEPLOY" --replicas=1 >/dev/null
  fi
}
trap cleanup EXIT
trap 'echo; echo "interrupted"; exit 1' INT TERM

# ---------------------------------------------------------------- one run
diagnostics() {  # $1 = run dir, $2 = pod name (may be empty)
  local d="$1/diagnostics" p="$2"
  mkdir -p "$d"
  $K get pods -l "$SEL" -o wide > "$d/pods.txt" 2>&1
  $K get events --sort-by=.lastTimestamp > "$d/events.txt" 2>&1
  if [ -n "$p" ]; then
    $K describe pod "$p" > "$d/describe.txt" 2>&1
    $K logs "$p" -c fetch-model > "$d/init.log" 2>&1
    $K logs "$p" -c "$CONTAINER" > "$d/server.log" 2>&1
    $K logs "$p" -c "$CONTAINER" --previous > "$d/server.previous.log" 2>&1
  fi
  echo "diagnostics: $d"
}

delete_model() {  # the server mounts /models read-only, so use a helper pod with the PVC read-write
  log "run $1: deleting $MODEL_PATH from PVC $MODEL_PVC (helper pod)"
  local o
  o=$(printf '{"spec":{"volumes":[{"name":"models","persistentVolumeClaim":{"claimName":"%s"}}],"containers":[{"name":"rm","image":"%s","command":["sh","-c","rm -f %s && ls -l /models"],"volumeMounts":[{"name":"models","mountPath":"/models"}]}]}}' \
      "$MODEL_PVC" "$PROBER_IMAGE" "$MODEL_PATH")
  $K run "model-rm-$$" --rm -i --quiet --restart=Never --image="$PROBER_IMAGE" --overrides="$o" ||
    { echo "could not delete the model via helper pod"; return 1; }
}

drop_page_cache() {
  sync && sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' || { echo "drop_caches failed (sudo expired? run sudo -v)"; return 1; }
}

run_once() {  # $1 = run number
  local n=$1 dir="$RUN_ROOT/run-$1" old_pods t0 t_prep="" pod
  mkdir -p "$dir"
  old_pods=$($K get pods -l "$SEL" -o jsonpath='{.items[*].metadata.name}')

  probe_start "$dir/prober.log"
  sleep 1   # a little pre-trigger baseline in the prober log

  case "$TRIGGER" in
    restart) t0=$(now); $K rollout restart deploy/"$DEPLOY" >/dev/null ;;
    delete)  t0=$(now); $K delete pod $old_pods --wait=false >/dev/null ;;
    scale)
      $K scale deploy/"$DEPLOY" --replicas=0 >/dev/null
      $K wait --for=delete pod -l "$SEL" --timeout=120s >/dev/null 2>&1 || { echo "old pod did not go away"; return 1; }
      if [ "$MODE" = cold-model ]; then
        delete_model "$n" || return 1
      fi
      if [ "$MODE" = cold-cache ]; then
        t_prep=$(now); drop_page_cache || return 1
        log "run $n: page cache dropped"
      fi
      t0=$(now); $K scale deploy/"$DEPLOY" --replicas=1 >/dev/null ;;
  esac
  log "run $n: triggered ($TRIGGER) — waiting for the new pod"

  # watch: poll pod + EndpointSlice; record when each state is first seen; fail fast
  WATCH_OUT="$dir/watch.json" OLD="$old_pods" NS="$NS" SEL="$SEL" SVC="$SVC" T0="$t0" TIMEOUT="$TIMEOUT" \
  python3 - <<'PY'
import json, os, subprocess, sys, time
ns, sel, svc, t0, timeout = os.environ["NS"], os.environ["SEL"], os.environ["SVC"], float(os.environ["T0"]), float(os.environ["TIMEOUT"])
old = set(os.environ["OLD"].split())
def kj(*args):
    r = subprocess.run(["kubectl", "-n", ns, *args, "-o", "json"], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout else {}
seen, pod_name, fail, polls = {}, None, None, 0
FATAL = {"ImagePullBackOff", "ErrImagePull", "ErrImageNeverPull", "CrashLoopBackOff",
         "CreateContainerConfigError", "CreateContainerError", "InvalidImageName"}
while time.time() - t0 < timeout:
    polls += 1
    pods = [p for p in kj("get", "pods", "-l", sel).get("items", []) if p["metadata"]["name"] not in old]
    now = time.time()  # stamp pod observations right after the pod fetch
    if pods:
        p = max(pods, key=lambda p: p["metadata"]["creationTimestamp"])
        pod_name = p["metadata"]["name"]
        seen.setdefault("pod_seen", now)
        st = p.get("status", {})
        conds = {c["type"]: c["status"] for c in st.get("conditions", [])}
        if conds.get("PodScheduled") == "True": seen.setdefault("scheduled_seen", now)
        if conds.get("Initialized") == "True": seen.setdefault("initialized_seen", now)
        cs = (st.get("containerStatuses") or [{}])[0]
        if "running" in cs.get("state", {}): seen.setdefault("running_seen", now)
        if cs.get("ready"): seen.setdefault("ready_seen", now)
        for s in (st.get("initContainerStatuses") or []) + (st.get("containerStatuses") or []):
            w = s.get("state", {}).get("waiting", {}).get("reason")
            term = s.get("state", {}).get("terminated", {})
            if w in FATAL: fail = f"{s['name']}: {w}"
            if s.get("restartCount", 0) > 0: fail = f"{s['name']}: restarted {s['restartCount']}x"
            if term and term.get("exitCode", 0) != 0: fail = f"{s['name']}: exited {term.get('exitCode')} ({term.get('reason')})"
        if conds.get("PodScheduled") != "True" and now - t0 > 30: fail = "not scheduled within 30 s"
        slices = kj("get", "endpointslices", "-l", f"kubernetes.io/service-name={svc}").get("items", [])
        t_eps = time.time()  # ...and endpoint observations right after their own fetch
        for es in slices:
            for e in es.get("endpoints") or []:
                if (e.get("targetRef") or {}).get("name") == pod_name and (e.get("conditions") or {}).get("ready"):
                    seen.setdefault("endpoint_ready_seen", t_eps)
                    # an endpoint is only ready once its pod is: the pod was Ready by now at the latest
                    seen["ready_seen"] = min(seen.get("ready_seen", t_eps), t_eps)
    if fail or ("ready_seen" in seen and "endpoint_ready_seen" in seen):
        break
    time.sleep(0.1)
ok = not fail and "ready_seen" in seen and "endpoint_ready_seen" in seen
out = {"ok": ok, "pod": pod_name, "polls": polls, "seen": {k: v - t0 for k, v in seen.items()},
       "error": fail or (None if ok else f"timeout after {timeout:.0f} s")}
json.dump(out, open(os.environ["WATCH_OUT"], "w"), indent=2)
print(f"  watch: {'ok' if ok else 'FAILED: ' + out['error']} (pod {pod_name}, {polls} polls)")
sys.exit(0 if ok else 1)
PY
  local watch_rc=$?
  pod=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pod"] or "")' "$dir/watch.json")

  # let the prober see a few seconds of steady state (and, for restart, the old pod's exit)
  if [ $watch_rc = 0 ]; then
    if [ "$TRIGGER" = restart ]; then
      $K rollout status deploy/"$DEPLOY" --timeout=120s >/dev/null 2>&1
      $K wait --for=delete pod $old_pods --timeout=120s >/dev/null 2>&1
    fi
    sleep 3
  fi
  probe_stop

  # collect raw material
  echo "{\"t0\": $t0, \"t_prep\": ${t_prep:-null}}" > "$dir/trigger.json"
  if [ -n "$pod" ]; then
    $K get pod "$pod" -o json > "$dir/pod.json" 2>/dev/null
    $K get events --field-selector involvedObject.name="$pod" -o json > "$dir/events.json" 2>/dev/null
    $K logs "$pod" -c fetch-model > "$dir/init.log" 2>/dev/null
    if [ "$BACKEND" = sim ]; then   # runtime timestamps: the simulator's own log has no start-relative clock
      $K logs "$pod" -c "$CONTAINER" --timestamps > "$dir/server.log" 2>/dev/null
    else
      $K logs "$pod" -c "$CONTAINER" > "$dir/server.log" 2>/dev/null
    fi
  fi
  if [ $watch_rc != 0 ]; then diagnostics "$dir" "$pod"; return 1; fi
  python3 - "$dir" "$MODE" "$TRIGGER" "$BACKEND" <<'PY'
import json, re, sys
from datetime import datetime
from pathlib import Path
d, mode, trigger, backend = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
trig = json.loads((d / "trigger.json").read_text()); t0 = trig["t0"]
watch = json.loads((d / "watch.json").read_text())
pod = json.loads((d / "pod.json").read_text())
events = json.loads((d / "events.json").read_text()).get("items", [])
ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() - t0 if s else None
st = pod["status"]
cond = {c["type"]: c.get("lastTransitionTime") for c in st.get("conditions", [])}
init = next((s for s in st.get("initContainerStatuses") or [] if s["name"] == "fetch-model"), {})
init_term = init.get("state", {}).get("terminated", {})
main = (st.get("containerStatuses") or [{}])[0]

# llama-server log lines look like "0.00.710.606 I srv  llama_server: model loaded" (m.ss.ms.us since start)
def log_t(pattern):
    for line in (d / "server.log").read_text(errors="replace").splitlines():
        m = re.match(r"\s*(\d+)\.(\d+)\.(\d+)\.(\d+)\s.*" + pattern, line)
        if m:
            mi, s, ms, us = map(int, m.groups()); return mi * 60 + s + ms / 1e3 + us / 1e6
init_log = (d / "init.log").read_text(errors="replace") if (d / "init.log").exists() else ""
pulls = [e.get("message", "") for e in events if e.get("reason") == "Pulled"]
unhealthy = sum(e.get("count", 1) or 1 for e in events if e.get("reason") == "Unhealthy")

# prober: "<epoch> <http code>" lines
probe = []
for line in (d / "prober.log").read_text().splitlines():
    parts = line.split()
    if len(parts) == 2:
        probe.append((float(parts[0]) - t0, parts[1]))
after = [(t, c) for t, c in probe if t >= 0]
errors = [(t, c) for t, c in after if c != "200"]
first_err = errors[0][0] if errors else None
first_ok_after_err = next((t for t, c in after if c == "200" and first_err is not None and t > first_err), None)

started = ts(main.get("state", {}).get("running", {}).get("startedAt"))
loaded, listening = log_t("model loaded"), log_t("listening on")
if backend == "sim":
    # "<RFC3339 ns> I1002 ... "Server starting" protocol="HTTP"": loaded = listening = first line -> HTTP up
    stamps = []
    for line in (d / "server.log").read_text(errors="replace").splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)\s(.*)", line)
        if m:
            frac = (m.group(2) or ".0")[:7]   # Python parses at most microseconds
            stamps.append((datetime.fromisoformat(m.group(1) + frac + m.group(3).replace("Z", "+00:00")).timestamp(), m.group(4)))
    http = next((t for t, text in stamps if "Server starting" in text and 'protocol="HTTP"' in text), None)
    if stamps and http is not None:
        loaded = listening = http - stamps[0][0]
        started = stamps[0][0] - t0   # first log line is a better process start than k8s' whole second
seen = watch["seen"]
tl = {
    "created": ts(pod["metadata"]["creationTimestamp"]),
    "scheduled": ts(cond.get("PodScheduled")),
    "init_started": ts(init.get("state", {}).get("terminated", {}).get("startedAt")),
    "init_finished": ts(init_term.get("finishedAt")),
    "container_started": started,
    "model_loaded": started + loaded if started is not None and loaded is not None else None,
    "ready_k8s": ts(cond.get("Ready")),
    "ready_seen": seen.get("ready_seen"),
    "endpoint_ready_seen": seen.get("endpoint_ready_seen"),
}
# Serving = first 200 after an outage, if the prober saw one. Otherwise the old pod kept answering
# (restart: by design; delete: preStop sleep + kube-proxy's fallback to terminating endpoints),
# and the new pod counts as serving once its endpoint is ready.
serving = first_ok_after_err if first_ok_after_err is not None else tl["endpoint_ready_seen"]
res = {
    "mode": mode, "trigger": trigger, "pod": watch["pod"],
    "timeline_s": {k: (round(v, 3) if v is not None else None) for k, v in tl.items()},
    "init": {"action": "download" if "downloading" in init_log else ("skip (present)" if "model present" in init_log else "?"),
             "seconds": round(tl["init_finished"] - tl["init_started"], 1) if tl["init_finished"] is not None and tl["init_started"] is not None else None},
    "image_pulls": pulls,
    "model_load_ms": round(loaded * 1000, 1) if loaded is not None else None,
    "listening_ms": round(listening * 1000, 1) if listening is not None else None,
    "startup_probe_failures": unhealthy,
    "probe_overhead_s": round(tl["ready_seen"] - tl["model_loaded"], 2) if tl["ready_seen"] is not None and tl["model_loaded"] is not None else None,
    "time_to_ready_s": round(tl["ready_seen"], 2) if tl["ready_seen"] is not None else None,
    "time_to_serving_s": round(serving, 2) if serving is not None else None,
    "prober": {"samples": len(after), "non_200": len(errors),
               "downtime_s": round(first_ok_after_err - first_err, 2) if first_ok_after_err is not None else (None if not errors else "no recovery seen"),
               "error_codes": sorted({c for _, c in errors})},
    "watch_polls": watch["polls"],
}
(d / "result.json").write_text(json.dumps(res, indent=2) + "\n")
t = res["timeline_s"]
f = lambda v: "     -" if v is None else f"{v:6.2f}"
print("  seconds after trigger · created/sched/init/started from k8s (1 s, rounded down) · ready/endpt polled (~0.5 s)")
print(f"  {'created':>9} {'sched':>6} {'init dur':>8} {'started':>7} {'loaded':>7} {'ready':>6} {'endpt':>6} {'serving':>7}   probe-fail  non-200  downtime")
init_s = f(res['init']['seconds']).strip() if res['init']['seconds'] is not None else "-"
print(f"  {f(t['created']):>9} {f(t['scheduled'])} {init_s:>8} {f(t['container_started']):>7} {f(t['model_loaded']):>7} "
      f"{f(t['ready_seen'])} {f(t['endpoint_ready_seen'])} {f(res['time_to_serving_s']):>7}   "
      f"{res['startup_probe_failures']:>10} {res['prober']['non_200']:>8} {str(res['prober']['downtime_s']):>9}")
print(f"  model load {res['model_load_ms']} ms (server log) · init: {res['init']['action']} {res['init']['seconds']} s · probe overhead {res['probe_overhead_s']} s")
PY
}

# ---------------------------------------------------------------- series
log "starting prober pod $PROBER"
start_prober
failed=0
for n in $(seq 1 "$RUNS"); do
  log "run $n/$RUNS"
  if ! run_once "$n"; then
    failed=1; log "run $n FAILED — stopping the series"; break
  fi
done

# summary + history + report
python3 - "$RUN_ROOT" "$OUT_ROOT/history.jsonl" "$MODE" "$TRIGGER" "$failed" <<'PY'
import json, statistics, sys
from pathlib import Path
root, hist, mode, trigger, failed = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5] == "1"
prov = json.loads((root / "provenance.json").read_text())
runs = [json.loads(p.read_text()) for p in sorted(root.glob("run-*/result.json"))]
def med(path):
    vals = []
    for r in runs:
        v = r
        for k in path.split("."): v = v.get(k) if isinstance(v, dict) else None
        if isinstance(v, (int, float)): vals.append(v)
    return round(statistics.median(vals), 2) if vals else None
keys = [("time_to_serving_s", "time to serving [s]"), ("time_to_ready_s", "time to Ready [s]"),
        ("timeline_s.created", "pod created [s]"), ("timeline_s.container_started", "container started [s]"),
        ("init.seconds", "init container [s]"), ("model_load_ms", "model load [ms]"),
        ("probe_overhead_s", "Ready - model loaded [s]"), ("startup_probe_failures", "startup probe failures"),
        ("prober.non_200", "non-200 responses via Service"), ("prober.downtime_s", "downtime [s]")]
summary = {k: med(k) for k, _ in keys}
rec = {"series": root.name, "mode": mode, "trigger": trigger, "runs_ok": len(runs), "failed": failed,
       **prov, "median": summary}
with hist.open("a") as f:
    f.write(json.dumps(rec) + "\n")
lines = [f"# Bring-up timing — {mode}, trigger {trigger}", "",
         f"- **when**: {root.name[:15]} · **runs ok**: {len(runs)}{' (series stopped by a failure)' if failed else ''}",
         f"- **chart**: {prov['helm'].get('chart')} rev {prov['helm'].get('revision')} · **image**: {prov['image']} · "
         f"**values sha**: {prov['values_sha256']} · **git**: {prov['git_commit']}{' (deploy/ dirty)' if prov['git_dirty'] else ''}",
         f"- **node**: {prov['node']} · **model**: {prov['model_path']}", "",
         "All times are seconds after the trigger unless noted. Kubernetes timestamps (created, container",
         "started, init) are whole seconds rounded down, so they can be slightly negative; Ready/endpoint",
         "are polled (~0.5 s); model load comes from the server log (ms); serving/downtime from a prober",
         "pod hitting the Service every ~0.1 s. With trigger `restart` the old pod keeps answering, so",
         "serving = new endpoint ready and non-200 should be 0.", "",
         "| metric | median | " + " | ".join(f"run {i+1}" for i in range(len(runs))) + " |",
         "|---|---:|" + "---:|" * len(runs)]
for k, label in keys:
    cells = []
    for r in runs:
        v = r
        for part in k.split("."): v = v.get(part) if isinstance(v, dict) else None
        cells.append("–" if v is None else str(v))
    lines.append(f"| {label} | {summary[k] if summary[k] is not None else '–'} | " + " | ".join(cells) + " |")
lines += ["", "Init action per run: " + ", ".join(r["init"]["action"] for r in runs) if runs else "",
          "", "Raw per run: `run-N/` (result.json, watch.json, pod.json, events.json, server.log, init.log, prober.log)."]
(root / "REPORT.md").write_text("\n".join(lines) + "\n")
print()
print(f"summary ({len(runs)} run(s), median):")
for k, label in keys:
    print(f"  {label:<32} {summary[k]}")
print(f"\nreport:  {root / 'REPORT.md'}\nhistory: {hist}")
PY
exit $failed
