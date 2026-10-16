#!/bin/sh
set -eu
ip route replace default via 169.254.0.1 dev eth1 onlink table 201
ip route replace default via 169.254.0.1 dev eth2 onlink table 202
