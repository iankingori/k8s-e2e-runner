#!/usr/bin/env bash
set -e

DIR="$(dirname $0)"
TRAEFIK_CHART_VERSION="22.0.0"
TRAEFIK_NAMESPACE="traefik"
SETUP_ACTION="${1:-install}"

helm repo update traefik
helm $SETUP_ACTION traefik traefik/traefik \
    --wait \
    --create-namespace \
    --namespace $TRAEFIK_NAMESPACE \
    --version $TRAEFIK_CHART_VERSION \
    --values $DIR/values.yaml
