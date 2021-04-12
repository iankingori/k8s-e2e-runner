#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

if [[ $# -ne 2 ]]; then
    echo "USAGE: $0 <CI_PACKAGES_BASE_URL> <CI_VERSION>"
    exit 1
fi

CI_PACKAGES_BASE_URL=$1
CI_VERSION=$2
CI_PACKAGES=("kubectl" "kubelet" "kubeadm")
CI_IMAGES=("kube-apiserver" "kube-controller-manager" "kube-proxy" "kube-scheduler")

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

echo "* testing CI version $CI_VERSION"

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
    crictl rmi "k8s.gcr.io/${CI_IMAGE}:v1.21.0"
done

echo "* checking binary versions"
echo "ctr version: $(ctr version)"
echo "kubeadm version: $(kubeadm version -o=short)"
echo "kubectl version: $(kubectl version --client=true --short=true)"
echo "kubelet version: $(kubelet --version)"
