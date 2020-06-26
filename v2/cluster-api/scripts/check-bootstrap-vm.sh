#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

if [[ ! -d /www ]]; then
    echo "The web server root directory is not present"
    exit 1
fi

if ! which docker &> /dev/null; then
    echo "Docker is not installed"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "Docker is not running"
    exit 1
fi

if ! docker ps --all --format '{{.Names}}' | grep -q nginx; then
    echo "Nginx container is not present"
    exit 1
fi

if [[ ! "$(docker inspect -f {{.State.Running}} nginx)" == "true" ]] ; then
    echo "Nginx container is not running"
    exit 1
fi

echo "Bootstrap VM is ready"
