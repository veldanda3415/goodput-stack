#!/bin/sh
set -eu
# EVPN-VXLAN tenants on leaf1 (devices); VTEP 10.200.0.11; rendered from intent
# tenant-a: VRF table 1001, L3VNI 50001, L2VNI 10101 10.220.11.0/24
for dev in vx10101 br10101 vx50001 br50001 tenant-a; do ip link del $dev 2>/dev/null || true; done
ip link add tenant-a type vrf table 1001
ip link set tenant-a up
ip link add br50001 type bridge
ip link set br50001 master tenant-a addrgenmode none
ip link add vx50001 type vxlan id 50001 local 10.200.0.11 dstport 4789 nolearning
ip link set vx50001 mtu 9000 master br50001 addrgenmode none
ip link set vx50001 type bridge_slave neigh_suppress on learning off
ip link set br50001 mtu 9000 up
ip link set vx50001 up
ip link add br10101 type bridge
ip link set br10101 master tenant-a
ip link set br10101 address 02:00:00:00:fe:01
ip link add vx10101 type vxlan id 10101 local 10.200.0.11 dstport 4789 nolearning
ip link set vx10101 mtu 9000 master br10101 addrgenmode none
ip link set vx10101 type bridge_slave neigh_suppress on learning off
ip link set br10101 mtu 9000 up
ip address replace 10.220.11.1/24 dev br10101
ip link set vx10101 up
# tenant-b: VRF table 1002, L3VNI 50002, L2VNI 10201 10.220.21.0/24
for dev in vx10201 br10201 vx50002 br50002 tenant-b; do ip link del $dev 2>/dev/null || true; done
ip link add tenant-b type vrf table 1002
ip link set tenant-b up
ip link add br50002 type bridge
ip link set br50002 master tenant-b addrgenmode none
ip link add vx50002 type vxlan id 50002 local 10.200.0.11 dstport 4789 nolearning
ip link set vx50002 mtu 9000 master br50002 addrgenmode none
ip link set vx50002 type bridge_slave neigh_suppress on learning off
ip link set br50002 mtu 9000 up
ip link set vx50002 up
ip link add br10201 type bridge
ip link set br10201 master tenant-b
ip link set br10201 address 02:00:00:00:fe:01
ip link add vx10201 type vxlan id 10201 local 10.200.0.11 dstport 4789 nolearning
ip link set vx10201 mtu 9000 master br10201 addrgenmode none
ip link set vx10201 type bridge_slave neigh_suppress on learning off
ip link set br10201 mtu 9000 up
ip address replace 10.220.21.1/24 dev br10201
ip link set vx10201 up
