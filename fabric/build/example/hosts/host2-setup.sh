#!/bin/sh
set -eu
sysctl -w net.ipv4.conf.all.rp_filter=2 >/dev/null
sysctl -w net.ipv4.conf.default.rp_filter=2 >/dev/null
ip link set dev eth1 up
ip address replace 10.210.0.6/30 dev eth1
ip route replace 10.210.0.4/30 dev eth1 src 10.210.0.6 table 101
ip route replace default via 10.210.0.5 dev eth1 table 101
ip rule add priority 101 from 10.210.0.6 table 101
ip link set dev eth2 up
ip address replace 10.210.1.6/30 dev eth2
ip route replace 10.210.1.4/30 dev eth2 src 10.210.1.6 table 102
ip route replace default via 10.210.1.5 dev eth2 table 102
ip rule add priority 102 from 10.210.1.6 table 102
