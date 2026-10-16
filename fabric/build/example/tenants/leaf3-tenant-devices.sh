#!/bin/sh
set -eu
# EVPN-VXLAN tenants on leaf3 (devices); VTEP 10.200.0.13; rendered from intent
# tenant-a: VRF table 1001, L3VNI 50001, L2VNI 10103 10.220.13.0/24
for dev in vx10103 br10103 vx50001 br50001 tenant-a; do ip link del $dev 2>/dev/null || true; done
ip link add tenant-a type vrf table 1001
ip link set tenant-a up
ip link add br50001 type bridge
ip link set br50001 master tenant-a addrgenmode none
ip link add vx50001 type vxlan id 50001 local 10.200.0.13 dstport 4789 nolearning
ip link set vx50001 mtu 9000 master br50001 addrgenmode none
ip link set vx50001 type bridge_slave neigh_suppress on learning off
ip link set br50001 mtu 9000 up
ip link set vx50001 up
ip link add br10103 type bridge
ip link set br10103 master tenant-a
ip link set br10103 address 02:00:00:00:fe:01
ip link add vx10103 type vxlan id 10103 local 10.200.0.13 dstport 4789 nolearning
ip link set vx10103 mtu 9000 master br10103 addrgenmode none
ip link set vx10103 type bridge_slave neigh_suppress on learning off
ip link set br10103 mtu 9000 up
ip address replace 10.220.13.1/24 dev br10103
ip link set vx10103 up
