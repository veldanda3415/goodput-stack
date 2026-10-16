#!/bin/sh
# Rendered from fabric/intent/fabric.yaml qos (EMULATED host-side equivalent).
# Classifies egress traffic on each rail NIC by DSCP into prio bands that
# mirror the switch classes. veth has no PFC, no buffers and no ECN marking;
# this proves classification only. Linux prio bands are strict priority, so
# the DWRR weights in the intent are NOT reproduced here.
set -eu
tc qdisc del dev eth1 root 2>/dev/null || true
tc qdisc add dev eth1 root handle 1: prio bands 3 priomap 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2
# cnp: DSCP 48 -> TC6 -> band 1:1
tc filter add dev eth1 parent 1: protocol ip prio 1 flower ip_tos 0xc0/0xfc classid 1:1
# roce: DSCP 26 -> TC3 -> band 1:2
tc filter add dev eth1 parent 1: protocol ip prio 2 flower ip_tos 0x68/0xfc classid 1:2
tc qdisc del dev eth2 root 2>/dev/null || true
tc qdisc add dev eth2 root handle 1: prio bands 3 priomap 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2
# cnp: DSCP 48 -> TC6 -> band 1:1
tc filter add dev eth2 parent 1: protocol ip prio 1 flower ip_tos 0xc0/0xfc classid 1:1
# roce: DSCP 26 -> TC3 -> band 1:2
tc filter add dev eth2 parent 1: protocol ip prio 2 flower ip_tos 0x68/0xfc classid 1:2
