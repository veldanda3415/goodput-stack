.RECIPEPREFIX = >
SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: deploy deploy-lint deploy-diff deploy-test help check-env cluster-info tree venv bench-engine bench-engine-list bench-engine-dry bench-engine-prune bench-engine-all bench-du bringup sim-test bench-sim bench-sim-all bench-sim-list bench-sim-dry bench-compare sim-watch sim-probe

help: ## List targets
> @grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-14s %s\n",$$1,$$2}'

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
