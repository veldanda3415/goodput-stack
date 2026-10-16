#!/bin/sh
set -eu
# EVPN-VXLAN tenants on leaf3 (ports); VTEP 10.200.0.13; rendered from intent
ip link set eth5 mtu 9000 master br10103 up
ip link set br10103 mtu 9000
i=0; until vtysh -c 'show bgp l2vpn evpn vni 50001' 2>/dev/null | grep -q '65000:50001'; do i=$((i+1)); [ $i -ge 60 ] && echo 'L3VNI 50001 lacks RT 65000:50001' >&2 && exit 1; sleep 1; done
