#!/bin/sh
set -eu
# EVPN-VXLAN tenants on leaf2 (ports); VTEP 10.200.0.12; rendered from intent
ip link set eth6 mtu 9000 master br10202 up
ip link set br10202 mtu 9000
i=0; until vtysh -c 'show bgp l2vpn evpn vni 50002' 2>/dev/null | grep -q '65000:50002'; do i=$((i+1)); [ $i -ge 60 ] && echo 'L3VNI 50002 lacks RT 65000:50002' >&2 && exit 1; sleep 1; done
