#!/bin/bash

# Create logs directory
LogDir=$(mktemp -d /tmp/k8s-logs-XXXXXXXX)
if [ ! -z $LogDir ]; then
  mkdir -p $LogDir
fi
cd $LogDir

get-service-logs() {
  journalctl -u $1 --no-pager > $2/$1.log
}

get-pod-logs() {
  kubectl --kubeconfig /root/.kube/config -n kube-system logs $1 > $2/$1.pod.log
}

# Gather docker data
docker-data() {
 if [ ! -z "docker-data" ]; then
   mkdir docker-data
 fi

 get-service-logs docker.service docker-data
}

# Gather kube systemd logs
k8s-services-logs() {
  if [ ! -z "services-logs" ]; then
    mkdir services-logs
  fi

  services=($(systemctl list-unit-files | grep kube | awk  -F " " '{print $1}'))
  services+=("etcd3.service")

  for i in "${services[@]}"
  do
    get-service-logs $i services-logs
  done
}

# Gather kube-system pods logs
k8s-pods-logs() {
  if [ ! -z "pods-logs" ]; then
    mkdir pods-logs
  fi

  pods=($(kubectl --kubeconfig /root/.kube/config -o=name -n kube-system get pods | sed "s/^.\{4\}//"))

  if (( ${#pods[@]} )); then
    for i in "${pods[@]}"
    do
      get-pod-logs $i pods-logs
    done
  else
   echo "No pods were found in kube-system namespace." > pods-logs/kube-system-pods.log
  fi
}

# Gather k8s data
k8s-data() {
  if [ ! -z "k8s-data" ]; then
    mkdir k8s-data
  fi

  kubectl '--kubeconfig' /root/.kube/config get pods '-A' '-o' wide > k8s-data/k8s-pods
  kubectl '--kubeconfig' /root/.kube/config get nodes '-o' wide > k8s-data/k8s-nodes
  kubectl '--kubeconfig' /root/.kube/config version > k8s-data/kubectl-version
}

# Gather journalctl logs
system-logs() {
  if [ ! -z "system-logs" ]; then
    mkdir system-logs
  fi

  journalctl > system-logs/journalctl.log
}

# Main
docker-data
k8s-services-logs
k8s-pods-logs
system-logs
k8s-data

# Archive logs
tar -czvf /tmp/k8s-logs.tar.gz -C $LogDir .

touch /tmp/collect-logs.done
sleep 3600
