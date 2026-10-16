#!/bin/sh
set -eu
tc qdisc replace dev eth1 root tbf rate 500mbit burst 125000 limit 625000
tc qdisc replace dev eth2 root tbf rate 500mbit burst 125000 limit 625000
