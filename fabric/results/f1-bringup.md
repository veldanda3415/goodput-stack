# F1 lab bring-up evidence

**Run:** 2026-10-15, WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`
**Status:** EMULATED (veth links and Linux kernel forwarding; no ASICs or line-rate claims)
**Runtime:** containerlab `0.78.2`, Podman `5.7.0`, `containerlab --runtime podman`. The containerlab 0.78.2 deploy docs call Podman experimental. `podman info` reported `rootless=true`; the requested rootful socket at `/run/podman/podman.sock` was not accessible to this user. The successful deployment used the Podman runtime and user-owned containers; no Docker Engine was present.

## Address plan

| Use | Prefix |
|---|---|
| Router loopbacks | `10.200.0.0/24` (`/32` per router) |
| Host-facing rail A and B subnets | `10.210.0.0/16` (eight `/30`s) |
| Containerlab management | `10.253.0.0/24` |
| Explicit exclusions | `10.42.0.0/16`, `10.43.0.0/16`, `10.89.0.0/24` |

The management range does not overlap the k3s service/pod ranges or the default Podman bridge. Fabric links use IPv6 link-local addressing only.

## Bring-up and BGP

After rendering, the measured deploy command started at `2026-10-15T14:49:32.433815444-0400` (epoch `1792090172.438505844`):

```bash
containerlab deploy --runtime podman -t fabric/build/topology.clab.yml
```

The BGP JSON field `peerUptimeEstablishedEpoch` showed the last of the 16 expected sessions established at epoch `1792090178` (`14:49:38 -0400`). Bring-up was therefore **about 5.6 seconds** from the deploy start, with the BGP epoch timestamp's one-second resolution. The all-router verification at `14:49:56` independently showed all peers Established.

The per-node summary command was:

```bash
containerlab exec --runtime podman --name goodput-fabric \
  --label clab-node-name=leaf1 --cmd 'vtysh -c "show bgp summary"'
```

The JSON form was run on all six routers to check state and timestamp:

```bash
containerlab exec --runtime podman --name goodput-fabric \
  --label clab-node-name=spine1 --format json --log-level error \
  --cmd 'vtysh -c "show bgp summary json"'
```

The maximum `peerUptimeEstablishedEpoch` by router was:

| Router | Latest peer establishment epoch |
|---|---:|
| spine1 | 1792090178 |
| spine2 | 1792090178 |
| leaf1 | 1792090177 |
| leaf2 | 1792090178 |
| leaf3 | 1792090176 |
| leaf4 | 1792090176 |

The same command was run on all six routers. Every state was `Established` (not `Policy`, `Active`, or `Idle`):

| Router | Local AS | Neighbor interfaces | State | Prefixes received per peer |
|---|---:|---|---|---:|
| spine1 | 65000 | eth1-eth4 | Established | 3 |
| spine2 | 65000 | eth1-eth4 | Established | 3 |
| leaf1 | 65101 | eth1-eth2 | Established | 10 |
| leaf2 | 65102 | eth1-eth2 | Established | 10 |
| leaf3 | 65103 | eth1-eth2 | Established | 10 |
| leaf4 | 65104 | eth1-eth2 | Established | 10 |

Elapsed-time calculation: `latest peerUptimeEstablishedEpoch - DEPLOY_START_EPOCH` = `1792090178 - 1792090172.438505844` = approximately `5.6 s`. The query script used to collect each node's maximum timestamp:

```python
import json
import subprocess

for node in ("spine1", "spine2", "leaf1", "leaf2", "leaf3", "leaf4"):
    output = subprocess.run(
        ["containerlab", "exec", "--runtime", "podman", "--name", "goodput-fabric",
         "--label", f"clab-node-name={node}", "--format", "json", "--log-level", "error",
         "--cmd", 'vtysh -c "show bgp summary json"'],
        check=True, capture_output=True, text=True,
    )
    peers = json.loads(output.stdout)[f"clab-goodput-fabric-{node}"][0]["stdout"]["ipv4Unicast"]["peers"]
    print(node, max(peer["peerUptimeEstablishedEpoch"] for peer in peers.values()))
```

There were 16 expected adjacencies in total (four per spine, two per leaf). Example `show bgp summary` rows from the run:

```text
spine1 (AS 65000):
eth1  4  65101  ... 00:00:19  3  13
eth2  4  65102  ... 00:00:18  3  13
eth3  4  65103  ... 00:00:19  3  13
eth4  4  65104  ... 00:00:19  3  13

leaf1 (AS 65101):
eth1  4  65000  ... 00:00:19  10  14
eth2  4  65000  ... 00:00:19  10  14
```

## BFD

Command run on each router: `vtysh -c "show bfd peers brief json"`. All expected peers were Up, on their intended fabric interfaces:

| Router | Expected peers | Up | Observed transmit/receive | Detect multiplier |
|---|---:|---:|---|---:|
| spine1, spine2 | 4 each | 4 each | 100/100 ms | 3 |
| leaf1, leaf2, leaf3, leaf4 | 2 each | 2 each | 100/100 ms | 3 |

Example leaf1 peer output:

```text
peer fe80::a8c1:abff:fee5:f434 ... interface eth2
Status: up
Local timers: Detect-multiplier 3, Receive interval 100ms, Transmission interval 100ms
peer fe80::a8c1:abff:fef6:4329 ... interface eth1
Status: up
Local timers: Detect-multiplier 3, Receive interval 100ms, Transmission interval 100ms
```

## IPv4 prefixes over IPv6 next hops and ECMP

Command: `vtysh -c "show ip route"` on leaf1. A remote-leaf route had two BGP next hops:

```text
B>* 10.200.0.12/32 [20/0] via fe80::a8c1:abff:fee5:f434, eth2, weight 1
  *                       via fe80::a8c1:abff:fef6:4329, eth1, weight 1
```

The same two next hops were present in the kernel (`ip route show`):

```text
10.200.0.12 nhid 28 proto bgp metric 20
    nexthop via inet6 fe80::a8c1:abff:fee5:f434 dev eth2 weight 1
    nexthop via inet6 fe80::a8c1:abff:fef6:4329 dev eth1 weight 1
```

Leaf1 also had two paths for each remote leaf loopback and every remote host `/30`. `show ip route` showed the remote prefixes in the BGP RIB; the kernel FIB showed `via inet6 fe80::...` on the uplinks.

## Host reachability and path

Same leaf, host1 rail A to host2 rail A:

```text
ping -I 10.210.0.2 -c 3 -W 2 10.210.0.6
3 packets transmitted, 3 received, 0% packet loss
rtt min/avg/max/mdev = 0.043/0.114/0.255/0.099 ms
```

Across leaves, host1 rail A to host3 rail A:

```text
ping -I 10.210.0.2 -c 3 -W 2 10.210.0.10
3 packets transmitted, 3 received, 0% packet loss
rtt min/avg/max/mdev = 0.096/0.114/0.126/0.013 ms
```

`traceroute -n -s 10.210.0.2 -m 5 10.210.0.10`:

```text
1  10.210.0.1
2  10.200.0.1
3  10.200.0.12
4  10.210.0.10
```

The host setup installs source-address policy rules and a per-NIC routing table so replies leave on the rail that owns the source address. Host `rp_filter=2` (loose) avoids strict reverse-path drops when ECMP selects an asymmetric return uplink; the routers use `rp_filter=0`.

## Fix found during bring-up

The first deployment formed BGP sessions, but `show bgp summary` reported `(Policy)` and no exchanged prefixes. FRR's eBGP policy guard was active. The renderer now installs explicit permit route-maps on the fabric peer-group in both directions. After redeployment, each leaf received 10 prefixes per spine and each spine received 3 prefixes per leaf. This is intentionally restricted to the isolated fabric peer-group, rather than disabling the eBGP policy guard globally.
