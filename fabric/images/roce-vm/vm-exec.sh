#!/bin/sh
set -eu

ssh_guest() {
    ssh -i /var/lib/vm/id_ed25519 \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -p 2222 \
        fabric@127.0.0.1 -- "$@"
}

elapsed=0
while ! ssh_guest test -f /var/lib/cloud/instance/boot-finished >/dev/null 2>&1; do
    if [ "$elapsed" -ge 600 ]; then
        printf 'VM guest did not finish cloud-init within 600 seconds\\n' >&2
        tail -n 80 /var/log/vm-serial.log >&2
        exit 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

exec ssh_guest "$@"
