#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

GO_VERSION="1.17.3"
KIND_BIN_URL="https://github.com/kubernetes-sigs/kind/releases/download/v0.11.1/kind-linux-amd64"

function retrycmd_if_failure() {
  set +o errexit
  retries=$1; wait_sleep=$2; timeout=$3; shift && shift && shift
  for i in $(seq 1 "$retries"); do
    if timeout "$timeout" "${@}"; then
      break
    fi
    if [[ $i -eq $retries ]]; then
      echo "Error: Failed to execute '$*' after $i attempts"
      set -o errexit
      return 1
    fi
    sleep "$wait_sleep"
  done
  echo "Executed '$*' $i times"
  set -o errexit
}

retrycmd_if_failure 5 10 5m sudo apt-get update
retrycmd_if_failure 5 10 5m sudo apt-get install -y \
  build-essential curl wget git libffi-dev libssl-dev \
  rsync unzip net-tools openssh-client vim jq

retrycmd_if_failure 5 10 5m curl -O https://dl.google.com/go/go${GO_VERSION}.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz
rm go${GO_VERSION}.linux-amd64.tar.gz
eval `cat /etc/environment`
echo "PATH=\"$PATH:/usr/local/go/bin:$HOME/go/bin\"" | sudo tee /etc/environment
echo "GOPATH=\"$HOME/go\"" | sudo tee -a /etc/environment

retrycmd_if_failure 5 10 5m sudo apt-get install -y \
  apt-transport-https ca-certificates gnupg-agent software-properties-common
retrycmd_if_failure 5 10 5m curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
retrycmd_if_failure 5 10 5m sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
retrycmd_if_failure 5 10 5m sudo apt-get install -y docker-ce docker-ce-cli containerd.io

retrycmd_if_failure 5 10 5m docker pull nginx:stable
mkdir -p $HOME/www
docker run --name nginx \
           --restart unless-stopped \
           -v $HOME/www:/usr/share/nginx/html:ro \
           -p 8081:80 \
           -d nginx:stable

retrycmd_if_failure 5 10 5m sudo curl -L -o /usr/local/bin/kind $KIND_BIN_URL
sudo chmod +x /usr/local/bin/kind

PUBLIC_IP=$(curl -s -H Metadata:true 'http://169.254.169.254/metadata/instance?api-version=2017-04-02' | \
            jq -r '.network.interface[0].ipv4.ipAddress[0].publicIpAddress')

cat <<EOF > /tmp/kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  apiServerAddress: "0.0.0.0"
  apiServerPort: 6443
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    apiVersion: kubeadm.k8s.io/v1beta2
    kind: ClusterConfiguration
    apiServer:
      certSANs:
      - ${PUBLIC_IP}
EOF
kind create cluster --config /tmp/kind-config.yaml --wait 15m
