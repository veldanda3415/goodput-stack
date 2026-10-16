#!/bin/sh
ip route flush table 201 2>/dev/null || true
ip route flush table 202 2>/dev/null || true
while ip rule show | grep -q '^5[0-9][0-9][0-9]:'; do ip rule del priority $(ip rule show | awk -F: '/^5[0-9][0-9][0-9]:/ {print $1; exit}'); done
