#!/bin/sh
set -eu
ip route replace default via 169.254.0.1 dev eth1 onlink table 201
ip route replace default via 169.254.0.1 dev eth2 onlink table 202
ip rule add priority 5001 from 10.210.0.10 to 10.210.0.2 table 202  # host3->host1 via eth2 (reverse of a pattern pair)
ip rule add priority 5002 from 10.210.0.10 to 10.210.0.6 table 201  # host3->host2 via eth1
ip rule add priority 5003 from 10.210.0.14 to 10.210.0.2 table 202  # host4->host1 via eth2
ip rule add priority 5004 from 10.210.0.14 to 10.210.0.6 table 201  # host4->host2 via eth1 (reverse of a pattern pair)
