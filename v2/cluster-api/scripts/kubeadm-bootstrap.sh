#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

sysctl -w net.bridge.bridge-nf-call-iptables=1
