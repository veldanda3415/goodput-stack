.RECIPEPREFIX = >
SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help check-env cluster-info tree

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
