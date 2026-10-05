# ADR 0002 — Gateway objects in the inference chart

- **Status:** accepted and done (2026-10-05): cut-over ran, `inf` rev 30 owns the Gateway

## Context

The gateway side was applied by hand:

- `kubectl apply -f deploy/gateway/gateway.yaml`: the Gateway `inference-gateway`, listeners http:80 + https:443 (443 had no cert).
- `helm install sim-pool …llm-d-router-gateway --version v0.9.0 -f deploy/gateway/epp-sim.values.yaml`.
- `helm install llamacpp-pool … -f deploy/gateway/epp-llamacpp.values.yaml`.

The chart source was not recorded. It is `oci://ghcr.io/llm-d/charts/llm-d-router-gateway` v0.9.0 (digest `sha256:60f4533b…`). `helm template` with the committed values reproduces both live manifests, apart from blank lines.

Goal: `helm upgrade inf … -f values-k3s.yaml` reproduces the gateway side declaratively, with per-environment values.

## Options

**A. Both EPPs as aliased dependencies of `inference`** (`simPoolEpp`, `llamacppPoolEpp`). Preferred at first: one release, one upgrade, one history.
**Rejected: not feasible with v0.9.0.** Every object name in the chart is derived from `.Release.Name` (`{{ .Release.Name }}-epp`, InferencePool `{{ .Release.Name }}`). There is no `nameOverride`/`fullnameOverride`. A test render of the two aliases under release `inf` produced every object twice with the same name: 2× `Deployment inf-epp`, 2× `InferencePool inf`, 2× `HTTPRoute inf`, and so on. It would also rename the live pools (`sim-pool` → `inf`), and the HTTPRoutes and probes reference those names. Revisit if upstream adds name overrides; that would be an upstream PR.

**B. Keep the two EPP releases; template only the Gateway in `inference`** ← chosen.
- The Gateway is rendered from `gateway.*` values (`enabled`, `name`, `className`, `listeners`). It is off in base `values.yaml` and on in `values-k3s.yaml`. k3d has no Gateway controller, so it stays off there.
- The EPP releases become reproducible through `make epp-deploy` / `make epp-diff` (chart URL + version pinned in the Makefile, values from `deploy/gateway/epp-*.values.yaml`).
- Cut-over is an **adoption, not a re-create**: label/annotate the live Gateway (`app.kubernetes.io/managed-by=Helm`, `meta.helm.sh/release-name=inf`, `meta.helm.sh/release-namespace=inference`), then `helm upgrade inf`. The Gateway keeps its UID, so the agentgateway proxy Deployment, the LB Service and the IP 192.168.117.204 are untouched. Expected outage: none.
- `deploy/gateway/gateway.yaml` was used once for cut-over step 1 (http-only) and then deleted; the chart is the source of truth.

**C. helmfile / umbrella with three releases.** Gives one command for everything, but adds a new tool for two `helm upgrade` lines. Deferred; the Makefile is enough for now.

## Tradeoffs of B

- Three Helm releases with three histories, not one. `helm rollback inf` does not roll back EPP config.
- The order matters on a fresh cluster: `make deploy` (Gateway) before `make epp-deploy` (HTTPRoutes attach to it). The `helm test` through the gateway (`inf-gateway-sanity-test`) fails until both exist, which is intended.
- Deleting release `inf` now deletes the Gateway, and with it the agentgateway proxy and the LB IP. Before this ADR it survived.

## Config reload

The EPP reads its plugins ConfigMap only at startup. v0.9.0 has no `checksum/config` annotation and no `podAnnotations` value (the deployment template has no annotation hook), so a checksum roll is not possible without forking the chart. Instead, `make epp-deploy` always runs `make epp-restart` (`kubectl rollout restart` of both EPPs). The upstream fix is a checksum annotation on the EPP pod template.

## https:443 (#17)

The 443 listener is removed from the lab values. Without a certificate agentgateway still reported it `Programmed=True`, but the TLS handshake failed: `curl -sk https://192.168.117.204/v1/models` → "unexpected eof while reading", curl exit 35. It looked healthy but couldn't serve. `values-k3s.yaml` carries a commented listener + cert-manager `Certificate` block for when TLS is needed.

## Cut-over runbook (ran 2026-10-05)

Before it, `helm upgrade inf` failed with "Gateway inference-gateway exists and cannot be imported into the current
release" (seen in `--dry-run=server`).

Why step 1 uses kubectl: Helm 4 applies server-side. The `https` listener is owned by field manager
`kubectl-client-side-apply`, so a Helm apply that just omits it would **not** remove it (`deploy/release.sh diff k3s`
showed only label/annotation changes, no listener removal). Remove it with the tool that owns it first.

```bash
helm -n inference history inf | tail -1                                     # expect rev 29
kubectl apply -f deploy/gateway/gateway.yaml                                # 1. http-only: drops the 443 listener
kubectl -n inference label    gateway inference-gateway app.kubernetes.io/managed-by=Helm          # 2. adopt
kubectl -n inference annotate gateway inference-gateway meta.helm.sh/release-name=inf \
    meta.helm.sh/release-namespace=inference kubectl.kubernetes.io/last-applied-configuration-
deploy/release.sh diff k3s                                                  # 3. expect labels only, listeners [http]
deploy/release.sh upgrade k3s                                               # 4. rev 30
kubectl -n inference get gateway inference-gateway -o jsonpath='{.metadata.uid} {.spec.listeners[*].name}'
                                                                            #    UID unchanged: 3d162e0a-…
helm test inf -n inference --logs                                           # 5. incl. inf-gateway-sanity-test
git rm deploy/gateway/gateway.yaml                                          # 6.
```

Result: Gateway UID `3d162e0a-0c40-422a-9147-27090dfd0f28` unchanged, generation 1 → 2, listeners `[http]`, LB Service
ports `80` only, IP 192.168.117.204 kept, `http:80` answered 200 right after step 1. Step 3 diff: two labels
(`app.kubernetes.io/part-of`, `helm.sh/chart`) on the Gateway, nothing deleted. `inf` rev 29 → 30, no pod restarted.
`helm test inf`: `inf-gateway-sanity-test`, `inf-llamacpp-sanity-test`, `inf-vllm-sim-sanity-test` all Succeeded.

Rollback: **never `helm rollback inf` to ≤ 29**. Those revisions have no Gateway, so the rollback deletes it, and with it the
proxy Deployment and LB Service (both have ownerReferences to the Gateway). Fix forward with a new revision instead.
The pre-cut-over manifest is in git: `git show db2ba0e:deploy/gateway/gateway.yaml`.
