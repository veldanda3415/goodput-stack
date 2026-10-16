#!/bin/sh
set -eu
ip route replace default via 169.254.0.1 dev eth1 onlink table 201
ip route replace default via 169.254.0.1 dev eth2 onlink table 202
ip rule add priority 5001 from 10.210.0.2 to 10.210.0.10 table 202  # host1->host3 via eth2
ip rule add priority 5002 from 10.210.0.2 to 10.210.0.14 table 202  # host1->host4 via eth2
ip rule add priority 5003 from 10.210.0.6 to 10.210.0.10 table 201  # host2->host3 via eth1
ip rule add priority 5004 from 10.210.0.6 to 10.210.0.14 table 201  # host2->host4 via eth1
