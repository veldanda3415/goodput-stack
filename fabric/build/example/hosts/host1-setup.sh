#!/bin/sh
set -eu
sysctl -w net.ipv4.conf.all.rp_filter=2 >/dev/null
sysctl -w net.ipv4.conf.default.rp_filter=2 >/dev/null
ip link set dev eth1 up
ip address replace 10.210.0.2/30 dev eth1
ip route replace 10.210.0.0/30 dev eth1 src 10.210.0.2 table 101
ip route replace default via 10.210.0.1 dev eth1 table 101
ip rule add priority 101 from 10.210.0.2 table 101
ip link set dev eth2 up
ip address replace 10.210.1.2/30 dev eth2
ip route replace 10.210.1.0/30 dev eth2 src 10.210.1.2 table 102
ip route replace default via 10.210.1.1 dev eth2 table 102
ip rule add priority 102 from 10.210.1.2 table 102
rdma link show rxe_host1_a/1 >/dev/null 2>&1 || rdma link add rxe_host1_a type rxe netdev eth1
rdma link show rxe_host1_b/1 >/dev/null 2>&1 || rdma link add rxe_host1_b type rxe netdev eth2
for v in /sys/class/infiniband_verbs/uverbs*; do n=${v##*/}; [ -e /dev/infiniband/$n ] || mknod /dev/infiniband/$n c $(tr : ' ' < $v/dev); done
