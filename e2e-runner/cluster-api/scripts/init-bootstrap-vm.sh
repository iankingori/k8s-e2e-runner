#!/usr/bin/env bash
set -o nounset
set -o pipefail
set -o errexit

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

sudo apt-get purge -y snapd

retrycmd_if_failure 5 10 5m sudo apt-get update
retrycmd_if_failure 5 10 5m sudo apt-get install -y \
  snapd build-essential curl wget git libffi-dev libssl-dev \
  rsync unzip net-tools openssh-client vim jq

sudo systemctl start snapd

sudo addgroup --system docker
sudo usermod -aG docker capi

retrycmd_if_failure 5 10 5m sudo snap install docker
retrycmd_if_failure 5 10 5m sudo snap install go --classic
retrycmd_if_failure 5 10 5m sudo snap install microk8s --classic

sudo microk8s.enable dns storage
retrycmd_if_failure 10 10 5m sudo microk8s.kubectl wait --for=condition=Ready --timeout 5m pods --all --all-namespaces

mkdir -p $HOME/www

cat <<EOF | sudo microk8s.kubectl apply -f -
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nginx-pv
  labels:
    type: local
spec:
  storageClassName: manual
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: "$HOME/www"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nginx-pvc
spec:
  storageClassName: manual
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: nginx
  labels:
    app: nginx
spec:
  volumes:
    - name: nginx-pv
      persistentVolumeClaim:
        claimName: nginx-pvc
  containers:
    - name: nginx
      image: nginx
      ports:
        - containerPort: 80
          name: "http-server"
      volumeMounts:
        - mountPath: "/usr/share/nginx/html"
          name: nginx-pv
---
apiVersion: v1
kind: Service
metadata:
  name: nginx-svc
spec:
  selector:
    app: nginx
  type: NodePort
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
      nodePort: 30000
EOF

sudo usermod -aG microk8s capi

PUBLIC_IP=$(curl -s -H Metadata:true 'http://169.254.169.254/metadata/instance?api-version=2017-04-02' | \
            jq -r '.network.interface[0].ipv4.ipAddress[0].publicIpAddress')
sudo sed -i "s/#MOREIPS/IP.100 = $PUBLIC_IP\n#MOREIPS/g" /var/snap/microk8s/current/certs/csr.conf.template
