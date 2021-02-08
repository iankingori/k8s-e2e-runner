#!/usr/bin/env bash
set -o errexit
set -o pipefail

echo "Waiting for vxlan devices..."
while true; do
    VXLAN_DEVS=$(ip -o link show type vxlan | awk '{print substr($2, 1, length($2)-1)}')
    if [ -n "${VXLAN_DEVS}" ]; then
        for dev in ${VXLAN_DEVS}; do
            /sbin/ifconfig "${dev}" mtu 1350
        done
        break
    fi
    sleep 5
done
