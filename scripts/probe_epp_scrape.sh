#!/usr/bin/env bash
# scripts/probe_epp_scrape.sh — 3 long streams through the gateway to llamacpp-pool (x-pool: cpu), sampling
# llama.cpp's own queue metrics next to what the EPP sees, every 3 s until the streams finish.
#
#   scripts/probe_epp_scrape.sh
#   N=4 MAX_TOKENS=800 scripts/probe_epp_scrape.sh
#
# Own port-forwards on their own ports (not 18080/19090), so forwards left open in your shell don't
# make these fail; both are stopped on exit, Ctrl-C included.
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # `sh script` runs dash, which has no arrays
set -uo pipefail

NS=${NS:-inference}
N=${N:-3}                         # concurrent streams (llama.cpp has 2 slots → the 3rd should defer)
MAX_TOKENS=${MAX_TOKENS:-1500}
MODEL=${MODEL:-qwen2.5-0.5b-instruct}
LLAMA_PORT=${LLAMA_PORT:-28080}
EPP_PORT=${EPP_PORT:-29090}
GW=${GW:-$(kubectl -n "$NS" get gateway inference-gateway -o jsonpath='{.status.addresses[0].value}')}
[ -n "$GW" ] || { echo "no address on Gateway inference-gateway" >&2; exit 2; }

OUT=$(mktemp -d)
FWD=()
STREAMS=()
cleanup() { kill "${FWD[@]}" "${STREAMS[@]}" 2>/dev/null; }
trap cleanup EXIT
trap 'exit 130' INT TERM

kubectl -n "$NS" port-forward svc/inf-llamacpp "$LLAMA_PORT:8080" >/dev/null 2>&1 & FWD+=($!)
kubectl -n "$NS" port-forward svc/llamacpp-pool-epp "$EPP_PORT:9090" >/dev/null 2>&1 & FWD+=($!)
for port in "$LLAMA_PORT" "$EPP_PORT"; do       # wait until each forward answers, max ~10 s
  for _ in $(seq 20); do curl -s -o /dev/null "localhost:$port/metrics" && continue 2; sleep 0.5; done
  echo "port-forward on :$port never came up" >&2; exit 2
done

echo "gateway $GW · $N streams × $MAX_TOKENS tokens · output in $OUT"
for i in $(seq "$N"); do
  curl -sSN "http://$GW/v1/chat/completions" -H 'Content-Type: application/json' -H 'x-pool: cpu' \
    -d '{"model":"'"$MODEL"'","stream":true,"max_tokens":'"$MAX_TOKENS"',"ignore_eos":true,
         "messages":[{"role":"user","content":"Count from 1 to 2000, one number per line. Run '"$i"'"}]}' \
    -o "$OUT/stream$i.txt" & STREAMS+=($!)
done

running() { local p; for p in "${STREAMS[@]}"; do kill -0 "$p" 2>/dev/null && return 0; done; return 1; }
t=0
while running; do
  sleep 3; t=$((t + 3)); echo "--- t=${t}s"
  curl -s "localhost:$LLAMA_PORT/metrics" | grep -E '^llamacpp:requests_(processing|deferred)'
  curl -s "localhost:$EPP_PORT/metrics" \
    | grep -E '^inference_pool_(average_(queue_size|running_requests)|per_pod_queue_size)'
done

wait "${STREAMS[@]}"
echo "--- done after ~${t}s"
for i in $(seq "$N"); do
  printf 'stream%s: %s chunks\n' "$i" "$(grep -c '^data: {' "$OUT/stream$i.txt" 2>/dev/null || echo 0)"
done
