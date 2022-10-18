#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

KIND_BIN_URL="https://github.com/kubernetes-sigs/kind/releases/download/v0.16.0/kind-linux-amd64"

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
  build-essential curl git libffi-dev libssl-dev \
  rsync net-tools openssh-client vim jq

retrycmd_if_failure 10 5 5 curl -s -L https://golang.org/VERSION\?m\=text -o /tmp/golang-version.txt
GO_VERSION=$(cat /tmp/golang-version.txt)
retrycmd_if_failure 5 10 5m curl -O https://dl.google.com/go/${GO_VERSION}.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf ${GO_VERSION}.linux-amd64.tar.gz
rm ${GO_VERSION}.linux-amd64.tar.gz
sudo ln -s /usr/local/go/bin/go /usr/local/bin/go
go version

retrycmd_if_failure 5 10 5m sudo apt-get install -y ca-certificates curl gnupg lsb-release
sudo mkdir -p /etc/apt/keyrings
retrycmd_if_failure 5 10 5m curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
retrycmd_if_failure 5 10 5m sudo apt-get update
retrycmd_if_failure 5 10 5m sudo apt-get install -y docker-ce docker-ce-cli containerd.io

retrycmd_if_failure 5 10 5m docker pull nginx:stable
mkdir -p $HOME/www
docker run --name nginx --restart unless-stopped \
           -v $HOME/www:/usr/share/nginx/html:ro -p 8081:80 \
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
    kind: ClusterConfiguration
    apiServer:
      certSANs:
      - ${PUBLIC_IP}
EOF
