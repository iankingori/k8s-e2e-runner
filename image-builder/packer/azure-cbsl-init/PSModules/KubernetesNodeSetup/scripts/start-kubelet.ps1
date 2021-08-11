$ErrorActionPreference = "Stop"

$global:KUBELET_ARGS = (Get-Content "/var/lib/kubelet/kubeadm-flags.env").Trim("KUBELET_KUBEADM_ARGS=`"")


$dockerdBin = Get-Command "docker" -ErrorAction SilentlyContinue
if($dockerdBin) {
    $netID = docker network ls -q -f name=host
    if($LASTEXITCODE) {
        Throw "Failed to list docker network"
    }
    if ($netID.Length -lt 1) {
        docker network create -d nat host
        if($LASTEXITCODE) {
            Throw "Failed to create docker host network"
        }
    }
}

Invoke-Expression (
    "C:\k\kubelet.exe $global:KUBELET_ARGS " +
    "--cert-dir=$env:SystemDrive\var\lib\kubelet\pki " +
    "--config=/var/lib/kubelet/config.yaml " +
    "--bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf " +
    "--kubeconfig=/etc/kubernetes/kubelet.conf " +
    "--hostname-override=$(hostname) " +
    "--pod-infra-container-image=`"${env:K8S_PAUSE_IMAGE}`" " +
    "--enable-debugging-handlers " +
    "--cgroups-per-qos=false " +
    "--enforce-node-allocatable=`"`" " +
    "--network-plugin=cni " +
    "--resolv-conf=`"`" " +
    "--log-dir=/var/log/kubelet " +
    "--logtostderr=false " +
    "--image-pull-progress-deadline=20m")
