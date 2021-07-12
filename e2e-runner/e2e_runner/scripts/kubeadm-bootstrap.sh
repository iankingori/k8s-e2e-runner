#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

if [[ $# -ne 4 ]]; then
    echo "USAGE: $0 <CI_PACKAGES_BASE_URL> <CI_VERSION> <FLANNEL_MODE> <K8S_BINS_BUILT>"
    exit 1
fi

CI_PACKAGES_BASE_URL=$1
CI_VERSION=$2
FLANNEL_MODE=$3
K8S_BINS_BUILT=$4

run_cmd_with_retry() {
    local RETRIES=$1
    local WAIT_SLEEP=$2
    local TIMEOUT=$3

    shift && shift && shift

    for i in $(seq 1 $RETRIES); do
        timeout $TIMEOUT ${@} && break || \
        if [ $i -eq $RETRIES ]; then
            echo "Error: Failed to execute \"$@\" after $i attempts"
            return 1
        else
            echo "Failed to execute \"$@\". Retrying in $WAIT_SLEEP seconds..."
            sleep $WAIT_SLEEP
        fi
    done
    echo Executed \"$@\" $i times;
}

update_k8s() {
    CI_PACKAGES=("kubectl" "kubelet" "kubeadm")
    CI_IMAGES=("kube-apiserver" "kube-controller-manager" "kube-proxy" "kube-scheduler")

    echo "Updating Kubernetes to version: $CI_VERSION"

    systemctl stop kubelet

    for CI_PACKAGE in "${CI_PACKAGES[@]}"; do
        PACKAGE_URL="$CI_PACKAGES_BASE_URL/$CI_VERSION/bin/linux/amd64/$CI_PACKAGE"
        echo "* downloading binary: $PACKAGE_URL"
        run_cmd_with_retry 10 3 10m curl --fail -Lo /usr/bin/$CI_PACKAGE $PACKAGE_URL
        chmod +x /usr/bin/$CI_PACKAGE
    done

    systemctl start kubelet

    CI_DIR="/tmp/k8s-ci"
    mkdir -p $CI_DIR
    for CI_IMAGE in "${CI_IMAGES[@]}"; do
        CI_IMAGE_URL="$CI_PACKAGES_BASE_URL/$CI_VERSION/images/$CI_IMAGE.tar"
        echo "* downloading package: $CI_IMAGE_URL"
        run_cmd_with_retry 10 3 10m curl --fail -Lo "$CI_DIR/${CI_IMAGE}.tar" $CI_IMAGE_URL
        ctr -n k8s.io images import "$CI_DIR/$CI_IMAGE.tar"
        ctr -n k8s.io images tag "k8s.gcr.io/${CI_IMAGE}-amd64:${CI_VERSION//+/_}" "k8s.gcr.io/${CI_IMAGE}:${CI_VERSION//+/_}"
        # remove unused image tag
        ctr -n k8s.io image remove "k8s.gcr.io/${CI_IMAGE}-amd64:${CI_VERSION//+/_}"
        # cleanup cached node image
        crictl rmi "k8s.gcr.io/${CI_IMAGE}:v1.21.2"
    done

    echo "Checking binary versions"
    echo "ctr version: $(ctr version)"
    echo "kubeadm version: $(kubeadm version -o=short)"
    echo "kubectl version: $(kubectl version --client=true --short=true)"
    echo "kubelet version: $(kubelet --version)"
}

set_nics_mtu() {
    for dev in $(find /sys/class/net -type l -not -lname '*virtual*' -printf '%f\n'); do
        /sbin/ifconfig "${dev}" mtu 1450
    done
}

catch() {
    # If errors happen, uninstall the kubelet. This will render the machine
    # not started, and the cluster-api MachineHealthCheck will replace it.
    apt-get purge kubelet -y
}

trap catch ERR

if [[ "$K8S_BINS_BUILT" = "True" ]]; then
    update_k8s
fi
if [[ "$FLANNEL_MODE" = "overlay" ]]; then
    set_nics_mtu
fi
