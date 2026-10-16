#!/bin/sh
tc qdisc del dev eth1 root 2>/dev/null || true
tc qdisc del dev eth2 root 2>/dev/null || true
tc qdisc del dev eth3 root 2>/dev/null || true
tc qdisc del dev eth4 root 2>/dev/null || true
