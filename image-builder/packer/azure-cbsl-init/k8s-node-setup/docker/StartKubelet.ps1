$global:KubeletArgs = (Get-Content "/var/lib/kubelet/kubeadm-flags.env").Trim("KUBELET_KUBEADM_ARGS=`"")

$netId = docker network ls -q -f name=host
if ($netId.Length -lt 1) {
    docker network create -d nat host
}

$cmd = ("C:\k\kubelet.exe $global:KubeletArgs " +
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
        "--feature-gates=`"IPv6DualStack=false`" " +
        "--image-pull-progress-deadline=20m")

Invoke-Expression $cmd
