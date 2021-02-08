#!/usr/bin/env bash
set -o errexit
set -o pipefail

for dev in $(find /sys/class/net -type l -not -lname '*virtual*' -printf '%f\n'); do
    /sbin/ifconfig "${dev}" mtu 1450
done
