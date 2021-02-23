$global:KubeletArgs = (Get-Content "/var/lib/kubelet/kubeadm-flags.env").Trim("KUBELET_KUBEADM_ARGS=`"")

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
        "--resolv-conf=`"`" " +
        "--log-dir=/var/log/kubelet " +
        "--logtostderr=false " +
        "--feature-gates=`"IPv6DualStack=false`" " +
        "--image-pull-progress-deadline=20m")

Invoke-Expression $cmd
