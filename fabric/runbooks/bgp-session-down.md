# BGP session down: ASN or interface mismatch

## Symptoms

Check `vtysh -c 'show bgp summary'` on both ends of the link. An interface
neighbor that remains `Active` rather than `Established` is not exchanging
routes; `PfxRcd` remains zero. In `vtysh -c 'show bgp neighbors eth1'`, useful
fields include the local and remote ASNs, `Connections established` / `dropped`,
the last reset reason, and the BFD state. Check both ends because an interface
or peer-AS mismatch can look different from each router.

The FRR image used by this lab reports stdout logging at debugging level, with
file and syslog logging disabled (`show logging`). Inspect the node's container
stdout with the matching container-engine context for daemon messages; do not
mistake the `vtysh` warning about missing `/etc/frr/vtysh.conf` or
`frr.conf processing failure: 11` for a BGP notification. That warning was
present on successful as well as failed queries in this lab. During this drill,
`containerlab exec` could query the nodes but the local Podman CLI did not list
them, so no daemon stdout log line was available to quote; the FRR peer state
below is the captured evidence rather than an inferred log message.

## ASN mismatch drill

On 2026-10-15, the generated `leaf1` config was changed from `router bgp 65101`
to `router bgp 65199`, then only `leaf1` was restarted:

```sh
sed -i 's/^router bgp 65101$/router bgp 65199/' fabric/build/frr/leaf1/frr.conf
containerlab restart --runtime podman -t fabric/build/topology.clab.yml --node leaf1
make fabric-test
```

The live suite detected the failure and reported:

```text
AssertionError: BGP session down: spine1:eth1 state=Active, remote AS=65101, expected 65101
5 failed, 9 passed
```

`spine1` showed `eth1` in `Active` with zero received prefixes. `leaf1` showed
local AS `65199`, `eth1` / `eth2` in `Active`, and zero received BGP messages.
The detailed peer output showed one established and one dropped connection on
the spine, `Waiting for peer OPEN`, and BFD down on the affected link. The
remaining failures (missing routes, BFD down, and host ping loss) were
downstream symptoms. The spine's rendered peer group requires remote AS
`65101`, so the altered leaf AS could not establish the intended eBGP session.

## Recovery

Regenerate the configs from the validated intent, restart the affected node,
and allow the BGP connect-retry timer to expire before treating an immediate
test failure as a persistent fault:

```sh
make fabric-render
containerlab restart --runtime podman -t fabric/build/topology.clab.yml --node leaf1
make fabric-test
```

In this drill the first test immediately after restart still failed while the
session was waiting for its next connect attempt. After 70 seconds, the full
suite passed (`14 passed in 7.50s`). The configured BGP connect-retry interval
is 120 seconds; inspect the live peer timer rather than assuming every restart
reconnects immediately.

For an interface mismatch, verify that both ends of the intended link are
`UP`, have link-local IPv6 addresses, and are the interfaces named in the
rendered FRR config and containerlab topology. Compare the peer table against
the intent before changing either side.
