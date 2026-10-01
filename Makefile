.RECIPEPREFIX = >
SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help check-env cluster-info tree venv bench-engine bench-engine-list bench-engine-dry bench-engine-prune bench-engine-all bench-du

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

bench-du: ## Disk used by benchmark results
> @du -sh benchmarks/results/* 2>/dev/null
