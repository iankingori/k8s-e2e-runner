#!/usr/bin/env bash
set -e

DIR="$(dirname $0)"
TRAEFIK_CHART_VERSION="25.0.0"
TRAEFIK_NAMESPACE="traefik"

helm repo update traefik
helm upgrade traefik traefik/traefik \
    --install \
    --wait \
    --create-namespace \
    --namespace $TRAEFIK_NAMESPACE \
    --version $TRAEFIK_CHART_VERSION \
    --values $DIR/values.yaml
