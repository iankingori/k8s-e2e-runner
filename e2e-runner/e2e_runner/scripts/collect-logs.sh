#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

LOGS_DIR="$(mktemp -d /tmp/k8s-logs-XXXXXXXX)"

export KUBECONFIG="/etc/kubernetes/admin.conf"


get_systemd_logs() {
    systemd_logs="$LOGS_DIR/systemd"
    mkdir -p "$systemd_logs"

    journalctl -u "docker.service" --no-pager > "$systemd_logs/docker.service.log"

    for service_name in $(systemctl list-unit-files | grep kube | awk  -F " " '{print $1}'); do
        journalctl -u "$service_name" --no-pager > "$systemd_logs/$service_name.log"
    done

    journalctl > "$systemd_logs/journalctl.log"
}

get_k8s_logs() {
    if ! kubectl version &> /dev/null; then
        echo "WARNING: Cannot query the Kubernetes API. Skipping Kubernetes logs collection"
        return
    fi

    k8s_logs="$LOGS_DIR/k8s"
    mkdir -p "$k8s_logs"

    kubectl get pods -A -o wide > "$k8s_logs/pods-list"
    kubectl get nodes -o wide > "$k8s_logs/nodes-list"
    kubectl version > "$k8s_logs/kubectl-version"

    for pod_name in $(kubectl -o=name -n kube-system get pods | cut -d '/' -f2); do
        kubectl -n kube-system logs "$pod_name" > "$k8s_logs/$pod_name-pod.log"
    done
}

get_systemd_logs
get_k8s_logs

tar -czvf /tmp/logs.tgz -C $LOGS_DIR .
