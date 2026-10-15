.RECIPEPREFIX = >
SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: deploy deploy-lint deploy-diff deploy-test help check-env cluster-info tree venv bench-engine bench-engine-list bench-engine-dry bench-engine-prune bench-engine-all bench-du bringup sim-test bench-sim bench-sim-all bench-sim-list bench-sim-dry bench-compare sim-watch sim-probe epp-deploy epp-diff epp-restart probe-p7 probe-burst probe-p8 epp-plugin-test epp-plugin-on epp-plugin-off obs-up obs-down obs-apply keda-up keda-down zero-up zero-down probe-zero t4-run

help: ## List targets
> @grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-14s %s\n",$$1,$$2}'

check-env: ## Print versions of the tools this repo uses
> @for t in git python3 kubectl helm k3s k3d podman; do \
>   if command -v $$t >/dev/null 2>&1; then \
>     printf "  %-8s " $$t; \
>     case $$t in \
>       kubectl) kubectl version --client 2>/dev/null | head -1 ;; \
>       helm)    helm version --short 2>/dev/null ;; \
>       k3s)     k3s --version 2>/dev/null | head -1 ;; \
>       k3d)     k3d version 2>/dev/null | head -1 ;; \
>       *)       $$t --version 2>/dev/null | head -1 ;; \
>     esac; \
>   else printf "  %-8s MISSING\n" $$t; fi; \
> done

cluster-info: ## Show current kube context, nodes and Helm releases
> @kubectl config current-context
> @kubectl get nodes -o wide
> @helm list -A

tree: ## Show repo layout (2 levels)
> @find . -maxdepth 2 -not -path './.git*' -not -name '.gitkeep' | sort

# ---- deploy (inference chart) ------------------------------------------------
# values.yaml (shared) + values-$(ENV).yaml; each env is pinned to its kube context.
ENV ?= k3s

deploy: ## Upgrade flow: lint -> diff -> confirm -> upgrade -> helm test (ENV=k3s|k3d)
> deploy/release.sh all $(ENV) $(ARGS)

deploy-lint: ## helm lint with the ENV's values
> deploy/release.sh lint $(ENV)

deploy-diff: ## What an upgrade would change on the live cluster (prints "no changes" if none)
> @deploy/release.sh diff $(ENV) || [ $$? -eq 1 ]

deploy-test: ## helm test against the ENV's cluster
> deploy/release.sh test $(ENV)

# ---- benchmarks -----------------------------------------------------------
# engine = client -> one inference server directly (no router, no k8s)
# system = client -> router -> backends on k8s (not built yet)
PY  := .venv/bin/python
EXP ?= smoke

venv: ## Create .venv with benchmark deps
> python3 -m venv .venv && $(PY) -m pip install -q -r benchmarks/requirements.txt

bench-engine: ## Engine benchmark (direct llama-server): make bench-engine EXP=ttft [ARGS="--set client.requests=5"]
> $(PY) -m benchmarks.engine.run $(EXP) $(ARGS)

bench-engine-all: ## Run every engine experiment back to back + index report [ARGS="--skip saturation"]
> $(PY) -m benchmarks.engine.run --all $(ARGS)

bench-engine-list: ## List engine experiments
> @$(PY) -m benchmarks.engine.run --list

bench-engine-dry: ## Show sweep points and server commands for EXP
> @$(PY) -m benchmarks.engine.run $(EXP) --dry-run $(ARGS)

bench-engine-prune: ## Prune raw files of old engine runs of EXP (summaries kept)
> $(PY) -m benchmarks.engine.run $(EXP) --prune

# sim = the same engine experiments against the in-cluster vLLM simulator (SIMULATED latency).
SIM_CFG := --config benchmarks/engine/configs/sim.yaml

sim-test: ## helm test the release (llama.cpp + simulator sanity pods)
> helm test inf -n inference --logs

SIM_URL = http://$$(kubectl -n inference get svc inf-vllm-sim -o jsonpath='{.spec.clusterIP}'):8000

sim-watch: ## Live simulator metrics (running/waiting, tok/s, server TTFT) - run beside a benchmark
> python3 scripts/watch_metrics.py --url $(SIM_URL) $(ARGS)

sim-probe: ## Queue probe against the simulator: make sim-probe ARGS="--n 6 --max-tokens 64"
> python3 scripts/queue_probe.py --url $(SIM_URL) --model qwen2.5-0.5b-instruct $(ARGS)

bench-sim: ## Engine experiment against the k3s vLLM simulator: make bench-sim EXP=ttft [ARGS=...]
> $(PY) -m benchmarks.engine.run $(SIM_CFG) $(EXP) $(ARGS)

bench-sim-all: ## Every simulator experiment back to back + index report
> $(PY) -m benchmarks.engine.run $(SIM_CFG) --all $(ARGS)

bench-sim-list: ## List simulator experiments
> @$(PY) -m benchmarks.engine.run $(SIM_CFG) --list

bench-sim-dry: ## Show sweep points and simulator overrides for EXP
> @$(PY) -m benchmarks.engine.run $(SIM_CFG) $(EXP) --dry-run $(ARGS)

bench-compare: ## Two runs side by side: make bench-compare A=<run dir> B=<run dir> [ARGS="--out x.md"]
> $(PY) -m benchmarks.engine.compare $(A) $(B) $(ARGS)

bench-du: ## Disk used by benchmark results
> @du -sh benchmarks/results/* 2>/dev/null

bringup: ## Pod bring-up timing after a chart change: make bringup [ARGS="--trigger delete --runs 2"]
> scripts/bringup_timing.sh $(ARGS)

# ---- gateway EPPs (one llm-d-router-gateway release per InferencePool) ------------------------
# Separate releases, not dependencies of the inference chart: the chart names every object after
# the release (docs/adr/0002-gateway-in-chart.md). The Gateway itself is in the inference chart.
EPP_CHART   = oci://ghcr.io/llm-d/charts/llm-d-router-gateway
EPP_VERSION = v0.9.0
EPP_POOLS   = sim-pool:epp-sim llamacpp-pool:epp-llamacpp

epp-diff: ## Render each EPP release and dry-run it against the cluster (server-side)
> @for p in $(EPP_POOLS); do r=$${p%%:*}; f=$${p##*:}; echo "== $$r"; \
>   helm upgrade $$r $(EPP_CHART) --version $(EPP_VERSION) -n inference -f deploy/gateway/$$f.values.yaml \
>     --dry-run=server >/dev/null && echo "  dry-run ok"; done

epp-deploy: ## helm upgrade --install both EPP releases from deploy/gateway/epp-*.values.yaml, then restart
> @for p in $(EPP_POOLS); do r=$${p%%:*}; f=$${p##*:}; \
>   helm upgrade --install $$r $(EPP_CHART) --version $(EPP_VERSION) -n inference \
>     -f deploy/gateway/$$f.values.yaml --wait || exit 1; done
> $(MAKE) epp-restart

# The EPP reads its plugins ConfigMap only at startup and the chart has no checksum/config pod
# annotation (and no podAnnotations value), so a values change needs an explicit restart.
epp-restart: ## Restart both EPPs so they re-read their ConfigMaps
> kubectl -n inference rollout restart deploy/sim-pool-epp deploy/llamacpp-pool-epp
> kubectl -n inference rollout status deploy/sim-pool-epp --timeout=120s
> kubectl -n inference rollout status deploy/llamacpp-pool-epp --timeout=120s

# ---- gateway probes (findings in deploy/gateway/GAPS.md) ---------------------------------------
probe-p7: ## P7: delete the agentgateway pod mid-stream (llamacpp-pool), 3 runs [ARGS="--grace-period 1"]
> $(PY) scripts/probe_p7_gateway_kill.py $(ARGS)

probe-burst: ## P9: N concurrent sim-pool requests inside one EPP refresh vs spaced control (SIMULATED) [ARGS="--n 8"]
> $(PY) scripts/probe_burst.py $(ARGS)

# ---- token-aware scoring on sim-pool (ADR 0003): upstream token-load-scorer, opt-in values switch ----
epp-plugin-test: ## Server-side dry-run of the sim-pool EPP with the token-load overlay (no Go plugin: upstream ships it)
> helm upgrade sim-pool $(EPP_CHART) --version $(EPP_VERSION) -n inference -f deploy/gateway/epp-sim.values.yaml -f deploy/gateway/epp-sim-token-load.values.yaml --dry-run=server >/dev/null && echo "dry-run ok"

epp-plugin-on: ## Enable token-load-scorer on sim-pool's EPP only, then restart it
> helm upgrade sim-pool $(EPP_CHART) --version $(EPP_VERSION) -n inference -f deploy/gateway/epp-sim.values.yaml -f deploy/gateway/epp-sim-token-load.values.yaml --wait
> kubectl -n inference rollout restart deploy/sim-pool-epp && kubectl -n inference rollout status deploy/sim-pool-epp --timeout=120s

epp-plugin-off: ## Back to the stock sim-pool EPP profile, then restart it
> helm upgrade sim-pool $(EPP_CHART) --version $(EPP_VERSION) -n inference -f deploy/gateway/epp-sim.values.yaml --wait
> kubectl -n inference rollout restart deploy/sim-pool-epp && kubectl -n inference rollout status deploy/sim-pool-epp --timeout=120s

probe-p8: ## P8: size-blind routing on the scratch p8-pool (SIMULATED) [ARGS="--label off-pin --load-path gateway-pin"]
> $(PY) scripts/probe_p8_size_blind.py $(ARGS)

# ---- T4 engine track on Kaggle (benchmarks/kaggle/, results in benchmarks/results/t4/) ----------
STAGE ?= smoke
t4-run: ## Push one T4 notebook stage to Kaggle, wait, download: make t4-run STAGE=baseline [ARGS="--resume <dir>"]
> $(PY) -m benchmarks.kaggle.run_kaggle --stage $(STAGE) $(ARGS)

# ---- observability + autoscaling (observability/README.md, autoscaling/README.md) -------------
# Versions: one release behind latest on 2026-10-14 (`helm search repo <chart> --versions`).
KPS_CHART   = prometheus-community/kube-prometheus-stack
KPS_VERSION = 92.6.0
KEDA_CHART   = kedacore/keda
KEDA_VERSION = 2.20.2

obs-up: ## Install kube-prometheus-stack (ns monitoring) + our monitors, rules, dashboards
> helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update >/dev/null
> helm upgrade --install kps $(KPS_CHART) --version $(KPS_VERSION) -n monitoring --create-namespace -f observability/values-kps.yaml --wait --timeout 10m
> $(MAKE) obs-apply

obs-apply: ## Apply ServiceMonitors/PodMonitors, PrometheusRules and the dashboard ConfigMap
> kubectl apply -f observability/servicemonitors/ -f observability/alerts/
> python3 observability/dashboards/dashboard.py build >/dev/null && python3 observability/dashboards/dashboard.py configmap | kubectl apply -f -

obs-down: ## Remove our monitors and the kube-prometheus-stack release (CRDs stay)
> -kubectl delete -f observability/servicemonitors/ -f observability/alerts/ --ignore-not-found
> -kubectl -n monitoring delete configmap inference-dashboard --ignore-not-found
> helm uninstall kps -n monitoring

keda-up: ## Install KEDA (ns keda), then apply the ScaledObjects in autoscaling/
> helm repo add kedacore https://kedacore.github.io/charts --force-update >/dev/null
> helm upgrade --install keda $(KEDA_CHART) --version $(KEDA_VERSION) -n keda --create-namespace -f autoscaling/values-keda.yaml --wait --timeout 5m
> kubectl apply -f autoscaling/scaledobject-llamacpp.yaml -f autoscaling/scaledobject-vllm-sim.yaml

keda-down: ## Delete the ScaledObjects (HPAs go with them; replicas stay where they are) and uninstall KEDA
> -kubectl delete -f autoscaling/scaledobject-llamacpp.yaml -f autoscaling/scaledobject-vllm-sim.yaml --ignore-not-found
> helm uninstall keda -n keda

# Scale-from-zero scratch pool (autoscaling/scale-from-zero/, GAPS.md P6): sim-zero at 0 replicas, EPP with flowControl.
zero-up: ## Deploy zero-pool: sim-zero (0 replicas) + EPP release with flowControl + its ServiceMonitor + min-0 ScaledObject
> kubectl apply -f autoscaling/scale-from-zero/sim-zero.yaml -f autoscaling/scale-from-zero/servicemonitor-zero-epp.yaml
> helm upgrade --install zero-pool $(EPP_CHART) --version $(EPP_VERSION) -n inference -f autoscaling/scale-from-zero/epp-zero.values.yaml --wait
> kubectl -n inference rollout restart deploy/zero-pool-epp && kubectl -n inference rollout status deploy/zero-pool-epp --timeout=120s
> kubectl apply -f autoscaling/scale-from-zero/scaledobject-sim-zero.yaml

zero-down: ## Remove the zero-pool scratch pool
> -kubectl delete -f autoscaling/scale-from-zero/scaledobject-sim-zero.yaml -f autoscaling/scale-from-zero/servicemonitor-zero-epp.yaml --ignore-not-found
> -helm uninstall zero-pool -n inference
> kubectl delete -f autoscaling/scale-from-zero/sim-zero.yaml --ignore-not-found

probe-zero: ## 0->1 through zero-pool (KEDA does the scale): make probe-zero ARGS="--n 5"
> $(PY) autoscaling/scale-from-zero/probe_zero.py $(ARGS)

# ---- scheduling (SIMULATED GPUs on k3d `gpusim`; kubeconfig ~/.kube/gpusim.yaml, never the k3s one) ----
.PHONY: gpusim-up gpusim-down gpusim-status gpusim-operator gpusim-kueue gpusim-health gpusim-health-run
gpusim-up: ## Create k3d cluster gpusim (1 server + 3 agents, k3s v1.36.2+k3s1; 2 agents = GPU pool t4)
> python3 scheduling/gpusim.py up
gpusim-down: ## Delete the gpusim cluster
> python3 scheduling/gpusim.py down
gpusim-status: ## Nodes of gpusim (refuses if context is not k3d-gpusim)
> python3 scheduling/gpusim.py status
gpusim-operator: ## Install fake-gpu-operator 0.2.1 (SIMULATED 2 x Tesla-T4 per t4 node): MODE=deviceplugin|dra
> python3 scheduling/gpusim.py operator $(MODE)
gpusim-kueue: ## Install Kueue 0.20.1 + team-a/team-b queues on gpusim; add ARGS=waitforpods for waitForPodsReady
> python3 scheduling/gpusim.py kueue $(ARGS)
gpusim-health: ## Run the SIMULATED GPU health controller (watches node condition GPUXidError) until Ctrl-C
> python3 scheduling/health_controller.py
gpusim-health-run: ## Scenario 04: inject fault, measure fence/evict/reschedule/remediate, N runs (RUNS=3)
> python3 scheduling/health_run.py $(or $(RUNS),3)
