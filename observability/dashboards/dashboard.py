#!/usr/bin/env python3
"""Build the inference Grafana dashboard and its sidecar ConfigMap.

  python3 observability/dashboards/dashboard.py build       # writes observability/dashboards/inference.json
  python3 observability/dashboards/dashboard.py configmap   # prints the ConfigMap (label grafana_dashboard=1)

inference.json is generated, edit this file instead. Metric names come from live /metrics scrapes
(observability/README.md, "Metric sources"). Every pool label is `pool` (added by our ServiceMonitors /
PodMonitor relabelling), so sim-pool and llamacpp-pool group the same way across engine, EPP and gateway.
Percentiles are always histogram_quantile over summed bucket rates, never averaged.
"""
import json, pathlib, sys

HERE = pathlib.Path(__file__).parent
OUT = HERE / "inference.json"
NS = 'namespace="inference"'
_id = 0


def panel(title, targets, desc, unit="short", x=0, y=0, w=12, h=8, kind="timeseries", **extra):
    global _id
    _id += 1
    p = {"id": _id, "type": kind, "title": title, "description": desc,
         "datasource": {"type": "prometheus", "uid": "prometheus"},
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
         "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": {"type": "prometheus", "uid": "prometheus"}}
                     for i, (e, l) in enumerate(targets)]}
    p.update(extra)
    return p


def row(title, y):
    global _id
    _id += 1
    return {"id": _id, "type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def q(quantile, metric, by="pool", rng="1m", sel=NS):
    return f'histogram_quantile({quantile}, sum by (le, {by}) (rate({metric}_bucket{{{sel}}}[{rng}])))'


SIM = "SIMULATED: llm-d-inference-sim v0.10.2, latencies are configured, not measured on a model."
NO_LLAMA_HIST = "llama.cpp b11146 exports no latency histograms (only counters/gauges), so there is no llamacpp-pool series here."


def panels():
    ps, y = [], 0
    ps.append(row("Latency (per pool, where the data exists)", y)); y += 1
    ps.append(panel("Engine TTFT p50 / p95", [
        (q(0.5, "vllm:time_to_first_token_seconds"), "p50 {{pool}} (engine)"),
        (q(0.95, "vllm:time_to_first_token_seconds"), "p95 {{pool}} (engine)")],
        f"Server-side TTFT from vllm:time_to_first_token_seconds (sim-pool only). {SIM} {NO_LLAMA_HIST} "
        "Engine TTFT excludes the gateway hop, EPP pick and network; client TTFT (scripts/, autoscaling/loadgen.py) includes them. "
        "Measured 2026-10-14 (observability/evidence/panels-20261014-222133.json): the sim's TTFT also EXCLUDES queue wait: "
        "engine TTFT p95 max 0.0855 s while client TTFT p50 was 1.54 s with up to 4 requests waiting. See 'Engine queue time'.",
        unit="s", x=0, y=y))
    ps.append(panel("Engine ITL p50 / p95", [
        (q(0.5, "vllm:inter_token_latency_seconds"), "p50 {{pool}} (engine)"),
        (q(0.95, "vllm:inter_token_latency_seconds"), "p95 {{pool}} (engine)")],
        f"vllm:inter_token_latency_seconds (sim-pool only). {SIM} {NO_LLAMA_HIST}", unit="s", x=12, y=y)); y += 8
    ps.append(panel("Engine queue time p50 / p95", [
        (q(0.5, "vllm:request_queue_time_seconds"), "p50 {{pool}} (engine)"),
        (q(0.95, "vllm:request_queue_time_seconds"), "p95 {{pool}} (engine)")],
        f"vllm:request_queue_time_seconds: time waiting for a batch slot, which the sim's TTFT histogram leaves out. "
        f"Client TTFT ~= queue time + engine TTFT + gateway/EPP/network. {SIM} {NO_LLAMA_HIST} "
        "(llama.cpp's wait shows only as llamacpp:requests_deferred.)", unit="s", x=0, y=y, w=24, h=7)); y += 7
    ps.append(panel("Gateway request duration p50 / p95 (end of stream, NOT TTFT)", [
        (q(0.5, "agentgateway_request_duration_seconds"), "p50 {{pool}} (gateway)"),
        (q(0.95, "agentgateway_request_duration_seconds"), "p95 {{pool}} (gateway)")],
        "agentgateway_request_duration_seconds, both pools. Measured on 2026-10-14: a 120-token stream's duration "
        "grew this histogram's sum by 1.9356 s vs client total 1.936 s and client TTFB 0.033 s, so it ends at the "
        "END of the stream. agentgateway v1.6.0 exports no TTFT/first-byte histogram for these routes "
        "(upstream_call_duration_seconds has no series). This is the only latency series for llamacpp-pool.",
        unit="s", x=0, y=y))
    ps.append(panel("Engine TTFT vs gateway e2e (sim-pool, p95)", [
        (q(0.95, "vllm:time_to_first_token_seconds", sel=f'{NS},pool="sim-pool"'), "engine TTFT p95"),
        (q(0.95, "vllm:e2e_request_latency_seconds", sel=f'{NS},pool="sim-pool"'), "engine e2e p95"),
        (q(0.95, "agentgateway_request_duration_seconds", sel=f'{NS},pool="sim-pool"'), "gateway e2e p95")],
        f"Side by side: what the engine measures vs what the gateway measures for the same requests. Gateway e2e − "
        f"engine e2e ≈ gateway + EPP + network overhead. No gateway TTFT exists to compare with engine TTFT. {SIM}",
        unit="s", x=12, y=y)); y += 8

    ps.append(row("Throughput and errors", y)); y += 1
    ps.append(panel("Output tokens/s", [
        (f'sum by (pool) (rate(vllm:generation_tokens_total{{{NS}}}[1m]))', "{{pool}} (vllm:generation_tokens_total)"),
        (f'sum by (pool) (rate(llamacpp:tokens_predicted_total{{{NS}}}[1m]))', "{{pool}} (llamacpp:tokens_predicted_total)")],
        f"Engine counters. sim-pool is {SIM}", x=0, y=y, w=8))
    ps.append(panel("Requests/s (gateway)", [
        (f'sum by (pool) (rate(agentgateway_requests_total{{{NS}}}[1m]))', "{{pool}}")],
        "agentgateway_requests_total by route→pool, all status codes. llama.cpp exports no request counter, so the "
        "gateway is the only per-request source for llamacpp-pool.", unit="reqps", x=8, y=y, w=8))
    ps.append(panel("Errors/s (gateway, status >= 400)", [
        (f'sum by (pool, status) (rate(agentgateway_requests_total{{{NS},status=~"[45].."}}[1m]))', "{{pool}} {{status}}")],
        "Non-2xx/3xx responses at the gateway, by pool and status. Note: a hard-killed stream (P7) is a 200 that "
        "ended early and does not show here.", unit="reqps", x=16, y=y, w=8)); y += 8

    ps.append(row("Engine state (queue, running, KV)", y)); y += 1
    ps.append(panel("Waiting / queued", [
        (f'sum by (pool) (vllm:num_requests_waiting{{{NS}}})', "{{pool}} vllm:num_requests_waiting"),
        (f'sum by (pool) (llamacpp:requests_deferred{{{NS}}})', "{{pool}} llamacpp:requests_deferred")],
        "Requests accepted by the engine but not yet in a slot/batch. Summed over replicas.", x=0, y=y, w=8))
    ps.append(panel("Running / processing", [
        (f'sum by (pool) (vllm:num_requests_running{{{NS}}})', "{{pool}} vllm:num_requests_running"),
        (f'sum by (pool) (llamacpp:requests_processing{{{NS}}})', "{{pool}} llamacpp:requests_processing")],
        "Requests holding a slot. sim max-num-seqs 2 per pod; llama.cpp --parallel 2.", x=8, y=y, w=8))
    ps.append(panel("KV-cache usage (sim-pool only)", [
        (f'max by (pool, pod) (vllm:kv_cache_usage_perc{{{NS}}})', "{{pod}}")],
        f"vllm:kv_cache_usage_perc (0-1). {SIM} It read 0 throughout the 2026-10-14 load runs (max 4 waiting), so the sim does not model KV pressure in this config. llama.cpp b11146 exports no KV-cache metric (GAPS.md P4), "
        "so llamacpp-pool has no series here on purpose.", unit="percentunit", x=16, y=y, w=8)); y += 8

    ps.append(row("Pools, EPP, replicas", y)); y += 1
    ps.append(panel("In-flight per pool (engine running + waiting)", [
        (f'sum by (pool) (vllm:num_requests_running{{{NS}}} + vllm:num_requests_waiting{{{NS}}})', "{{pool}}"),
        (f'sum by (pool) (llamacpp:requests_processing{{{NS}}} + llamacpp:requests_deferred{{{NS}}})', "{{pool}}")],
        "Engine-side in-flight. The gateway exports no in-flight gauge.", x=0, y=y, w=8))
    ps.append(panel("EPP health", [
        (f'up{{{NS},job=~".+-pool-epp"}}', "scrape up {{pool}}"),
        (f'kube_deployment_status_replicas_available{{{NS},deployment=~".+-pool-epp"}}', "available {{deployment}}"),
        (f'llm_d_epp_ready_endpoints{{{NS}}}', "ready endpoints seen by EPP {{name}}")],
        "EPP scrape up, available replicas, and how many pool endpoints the EPP considers ready. llm-d-router-gateway "
        "v0.9.0 exports no scheduling-decision latency and no request counter (live /metrics, 2026-10-14). "
        "When the EPP has 0 replicas the gateway FAILS OPEN (GAPS.md P2): requests still succeed, load-blind; see alert EPPUnavailableFailOpen.",
        x=8, y=y, w=8))
    ps.append(panel("Replicas per deployment", [
        (f'kube_deployment_status_replicas_available{{{NS}}}', "{{deployment}} available"),
        (f'kube_deployment_spec_replicas{{{NS}}}', "{{deployment}} desired")],
        "kube-state-metrics. Desired vs available shows scale-up lag (KEDA/HPA).", x=16, y=y, w=8)); y += 8
    ps.append(panel("Gateway pre-upstream processing (includes the EPP ext-proc call)", [
        (f'sum by (pool) (rate(agentgateway_request_processing_seconds_sum{{{NS}}}[1m])) / '
         f'sum by (pool) (rate(agentgateway_request_processing_seconds_count{{{NS}}}[1m]))', "mean {{pool}}"),
        (q(0.95, "agentgateway_request_processing_seconds"), "p95 {{pool}}")],
        "The EPP exports no decision latency, so this is the proxy. Evidence (observability/alert_test.py, "
        "2026-10-14, sim-pool): mean 1.354 ms with the EPP up (n=55) vs 0.21 ms with it scaled to 0 (FailOpen, "
        "n=103), so ~1.1 ms of this is the ext-proc round trip. The histogram's lowest bucket is 1 ms, so the "
        "p95 is coarse; the mean (sum/count, not an average of percentiles) is the better read.",
        unit="s", x=0, y=y, w=24, h=7)); y += 7

    ps.append(row("Autoscaling: replicas vs queue vs TTFT", y)); y += 1
    for i, (pool, dep, queue, extra) in enumerate([
            ("sim-pool", "inf-vllm-sim", f'sum(vllm:num_requests_waiting{{{NS}}}) + sum(vllm:num_requests_running{{{NS}}})',
             (q(0.95, "vllm:time_to_first_token_seconds", sel=f'{NS},pool="sim-pool"', by="pool"), "engine TTFT p95 (s)")),
            ("llamacpp-pool", "inf-llamacpp", f'sum(llamacpp:requests_deferred{{{NS}}}) + sum(llamacpp:requests_processing{{{NS}}})',
             (q(0.95, "agentgateway_request_duration_seconds", sel=f'{NS},pool="llamacpp-pool"', by="pool"), "gateway e2e p95 (s), no TTFT metric"))]):
        ps.append(panel(f"{pool}: replicas vs queue vs latency", [
            (f'kube_deployment_spec_replicas{{{NS},deployment="{dep}"}}', "desired replicas"),
            (f'kube_deployment_status_replicas_available{{{NS},deployment="{dep}"}}', "available replicas"),
            (queue, "queue (running + waiting), the KEDA metric"),
            extra],
            "The KEDA trigger metric (autoscaling/scaledobject-*.yaml) against replica count and latency. "
            "Client TTFT per step is in autoscaling/results/ (loadgen.py). " + (SIM if pool == "sim-pool" else NO_LLAMA_HIST),
            x=12 * i, y=y, w=12, h=9,
            fieldConfig={"defaults": {"unit": "short"}, "overrides": [
                {"matcher": {"id": "byRegexp", "options": ".*\\(s\\).*"},
                 "properties": [{"id": "custom.axisPlacement", "value": "right"}, {"id": "unit", "value": "s"}]}]}))
    return ps


def dashboard():
    return {"uid": "goodput-inference", "title": "goodput-stack / inference", "tags": ["goodput-stack"],
            "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "10s",
            "time": {"from": "now-30m", "to": "now"},
            "description": "Gateway, EPP and engine metrics per InferencePool. sim-pool is SIMULATED.",
            "panels": panels()}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        OUT.write_text(json.dumps(dashboard(), indent=2) + "\n")
        print(f"wrote {OUT}")
    elif cmd == "configmap":
        body = OUT.read_text()
        cm = {"apiVersion": "v1", "kind": "ConfigMap",
              "metadata": {"name": "inference-dashboard", "namespace": "monitoring",
                           "labels": {"grafana_dashboard": "1", "app.kubernetes.io/part-of": "goodput-stack"}},
              "data": {"inference.json": body}}
        print(json.dumps(cm))
    else:
        sys.exit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
