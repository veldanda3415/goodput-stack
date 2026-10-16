#!/bin/sh
set -eu
# EVPN-VXLAN tenants on leaf4 (devices); VTEP 10.200.0.14; rendered from intent
# tenant-b: VRF table 1002, L3VNI 50002, L2VNI 10204 10.220.24.0/24
for dev in vx10204 br10204 vx50002 br50002 tenant-b; do ip link del $dev 2>/dev/null || true; done
ip link add tenant-b type vrf table 1002
ip link set tenant-b up
ip link add br50002 type bridge
ip link set br50002 master tenant-b addrgenmode none
ip link add vx50002 type vxlan id 50002 local 10.200.0.14 dstport 4789 nolearning
ip link set vx50002 mtu 9000 master br50002 addrgenmode none
ip link set vx50002 type bridge_slave neigh_suppress on learning off
ip link set br50002 mtu 9000 up
ip link set vx50002 up
ip link add br10204 type bridge
ip link set br10204 master tenant-b
ip link set br10204 address 02:00:00:00:fe:01
ip link add vx10204 type vxlan id 10204 local 10.200.0.14 dstport 4789 nolearning
ip link set vx10204 mtu 9000 master br10204 addrgenmode none
ip link set vx10204 type bridge_slave neigh_suppress on learning off
ip link set br10204 mtu 9000 up
ip address replace 10.220.24.1/24 dev br10204
ip link set vx10204 up
