# Fabric telemetry

## Working local fallback

The available path is a host-side Python exporter plus a standalone local
Prometheus container. It is **EMULATED** telemetry: Linux/veth interface
counters, Linux qdisc counters when present, and FRR BGP/BFD state. It is not
gNMI, switch ASIC telemetry, PFC state, or hardware link utilization.

With the containerlab fabric running:

```bash
make telemetry-up
curl -fsS http://127.0.0.1:9109/metrics
curl -fsS 'http://127.0.0.1:9098/api/v1/targets'
python3 -m fabric.telemetry.export_panels --minutes 10 \
  --out fabric/telemetry/e5-panels.json
make telemetry-down
```

`make telemetry-up` starts the exporter on `127.0.0.1:9109` and Prometheus
on `127.0.0.1:9098`. Prometheus uses a 10-second scrape interval and
8-second scrape timeout. The exporter uses Python's standard library and
`containerlab exec` to read leaf `ip -j -s link`, leaf `tc -s -j qdisc`,
and FRR JSON BGP/BFD state. A scrape may take several seconds because it
queries the lab nodes serially. The service manager uses the pinned Podman
image below; it does not create or modify Kubernetes resources and was not
connected to k3s.

| Component | Pin / version | Source |
|---|---|---|
| Exporter | Project Python code; Python 3.14.4 in the recorded run; standard library only | [Exporter](./exporter.py); `containerlab exec` through the existing Podman runtime |
| Prometheus | `docker.io/prom/prometheus:v3.8.1@sha256:2b6f734e372c1b4717008f7d0a0152316aedd4d13ae17ef1e3268dbfaf68041b` | [Prometheus image](https://hub.docker.com/r/prom/prometheus/tags); scrape configuration in [prometheus.yml](./prometheus.yml) |

The dashboard is [fabric.json](../../observability/dashboards/fabric.json).
It shows leaf uplink TX rates, max/mean imbalance across each leaf's two
uplinks, interface discards, qdisc ECN marks when an active qdisc exposes
them, and BGP/BFD state. Rates are byte-counter rates on emulated links, not
utilization percentages. The exporter reads qdisc mark/drop counters only
while those qdiscs exist; the dashboard can therefore have no ECN series
outside an active RED test.

The recorded panel export in [e5-panels.json](./e5-panels.json) queries
Prometheus over the E5 telemetry-pilot window. It contains 52 datapoints for
uplink traffic, imbalance, and discards; 16 BGP series and 16 BFD series
reported state `1`. No ECN series appeared because the E5 window had no RED
qdisc active. The **EMULATED** pilot is also retained in
[e5-telemetry-pilot.json](./e5-telemetry-pilot.json); its traffic result is
not hardware performance.

## gNMI attempt and remaining work

FRR does not provide the required gNMI server. A pinned Nokia SR Linux
24.10.1 image was attempted as a containerlab node:

`ghcr.io/nokia/srlinux:24.10.1@sha256:d5ad80fd6c611f94ac8ff31a904bc7b6baabd16719175768ed403b64aac8247c`

The gNMIc image inspected/pulled for the planned client was:

`ghcr.io/openconfig/gnmic:0.40.0@sha256:d98466c1c97f35297be0055050541b2e5c2fc7273d022cf0da8554fcbe5be5ec`

No gNMI subscription ran. With containerlab 0.78.2 and Podman, deployment
failed during post-deploy configuration copy with `Client not set in
context`; cleanup also reported Netavark `No such device`. A direct rootless
SR Linux container exited after its default `/bin/bash` returned. The
failure was not resolved to an SR Linux protocol-interoperability result:
the node never became usable for this test. No topology node, scrape config,
or Kubernetes object remains from the attempt.

The tested fallback is therefore the Python exporter for this project's
Linux/FRR nodes. SR Linux and gNMI are **not operational** here. The
intended upstream references for a future attempt are:

- containerlab's [Nokia SR Linux kind](https://containerlab.dev/manual/kinds/srl/)
  and [topology node/link model](https://containerlab.dev/manual/topo-def-file/);
- Nokia SR Linux 24.10 [gNMI](https://documentation.nokia.com/srlinux/24-10/books/system-mgmt/gnmi.html)
  and [BGP](https://documentation.nokia.com/srlinux/24-10/books/routing-protocols/bgp.html)
  documentation;
- gNMIc's [subscriptions](https://gnmic.openconfig.net/user_guide/subscriptions/)
  and [Prometheus output](https://gnmic.openconfig.net/user_guide/outputs/prometheus/)
  documentation.

The next step is to run SR Linux in a supported containerlab environment,
verify its gNMI service and BGP/BFD interaction, then wire a reachable
Prometheus scrape target. Until that succeeds, keep gNMI claims out of the
dashboard and treat all current telemetry as **EMULATED** exporter data.
