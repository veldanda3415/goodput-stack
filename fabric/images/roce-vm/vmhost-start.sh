#!/bin/sh
set -eu

config=/run/vm/config
. "$config"

waited=0
until ip link show dev eth1 >/dev/null 2>&1; do
    if [ "$waited" -ge 30 ]; then
        printf 'containerlab did not attach the VM rail interface eth1 within 30 seconds\\n' >&2
        exit 1
    fi
    sleep 1
    waited=$((waited + 1))
done

ip link add br-fabric type bridge
ip link set eth1 up
ip link set eth1 master br-fabric
ip tuntap add dev tap0 mode tap
ip link set tap0 master br-fabric
ip link set tap0 up
ip link set br-fabric up

mkdir -p /var/lib/vm
ssh-keygen -q -t ed25519 -N "" -C "$VM_NAME" -f /var/lib/vm/id_ed25519
public_key=$(cat /var/lib/vm/id_ed25519.pub)
sed "s|__VM_SSH_PUBLIC_KEY__|\"$public_key\"|" /run/vm/user-data > /var/lib/vm/user-data
qemu-img create -q -f qcow2 -F qcow2 -b /opt/debian-13-generic-amd64.qcow2 /var/lib/vm/disk.qcow2
cloud-localds -N /run/vm/network-config /var/lib/vm/seed.iso /var/lib/vm/user-data /run/vm/meta-data

if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    accelerator=kvm
    cpu=host
else
    accelerator=tcg
    cpu=max
fi

qemu-system-x86_64 \
    -name "$VM_NAME" \
    -machine "accel=$accelerator" \
    -cpu "$cpu" \
    -smp "$VM_CPUS" \
    -m "${VM_MEMORY_MIB}M" \
    -drive "file=/var/lib/vm/disk.qcow2,if=virtio,format=qcow2" \
    -drive "file=/var/lib/vm/seed.iso,media=cdrom,readonly=on" \
    -netdev user,id=mgmt,hostfwd=tcp:127.0.0.1:2222-:22 \
    -device "virtio-net-pci,netdev=mgmt,mac=$VM_MANAGEMENT_MAC" \
    -netdev tap,id=fabric,ifname=tap0,script=no,downscript=no \
    -device "virtio-net-pci,netdev=fabric,mac=$VM_FABRIC_MAC" \
    -device virtio-rng-pci \
    -display none \
    -monitor none \
    -serial file:/var/log/vm-serial.log \
    -daemonize \
    -pidfile /var/lib/vm/qemu.pid

tail -F /var/log/vm-serial.log
