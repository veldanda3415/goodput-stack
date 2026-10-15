# DRAFT (not filed): agentgateway - ext_proc call is cancelled at 10 s and `AgentgatewayPolicy` extProc has no timeout field (#26)

Target repo: agentgateway/agentgateway. Version: v1.6.0. Evidence is from this repo (SIMULATED backend, daily k3s).

**What we saw.** With the llm-d EPP (Gateway API Inference Extension) as ext_proc and its Flow Control feature gate on, the EPP
holds a request while the pool has 0 endpoints. agentgateway ends the held ext_proc call at 10.0 s and returns
`HTTP 500: ext_proc failed: no more response messages` (`deploy/gateway/GAPS.md` P6 update, `autoscaling/README.md`).

**What we looked for.** The `AgentgatewayPolicy` CRD has `requestTimeout`, `backendRequestTimeout`, `responseIdleTimeout`
(`controller/api/v1alpha1/agentgateway/agentgateway_policy_types.go` ~l.2624) but the extProc config has no timeout field.
We did not find the source of the 10 s: `crates/agentgateway/src/http/ext_proc.rs` and `ext_proc/{channel,processing}.rs`
contain no timeout constant (grep `timeout`, `from_secs`). We therefore do not know whether it is a default route timeout, a
gRPC deadline or something else.

**Ask.** (1) Document where the 10 s comes from. (2) Add a configurable timeout on the extProc policy (or state that
`requestTimeout` applies and how they interact), so a scale-from-zero hold of 20-60 s is possible.

**Repro.** EPP with `featureGates: [flowControl]`, pool scaled to 0, one request through the gateway: 500 at ~10.0 s.
