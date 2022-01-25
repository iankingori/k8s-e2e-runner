$FileContent = Get-Content -Path "/var/lib/kubelet/kubeadm-flags.env"
$kubeAdmArgs = $FileContent.TrimStart('KUBELET_KUBEADM_ARGS=').Trim('"')

$args = "--cert-dir=$env:SYSTEMDRIVE/var/lib/kubelet/pki",
        "--config=$env:SYSTEMDRIVE/var/lib/kubelet/config.yaml",
        "--bootstrap-kubeconfig=$env:SYSTEMDRIVE/etc/kubernetes/bootstrap-kubelet.conf",
        "--kubeconfig=$env:SYSTEMDRIVE/etc/kubernetes/kubelet.conf",
        "--hostname-override=$(hostname)",
        "--pod-infra-container-image=`"k8s.gcr.io/pause:3.6`"",
        "--enable-debugging-handlers",
        "--cgroups-per-qos=false",
        "--enforce-node-allocatable=`"`"",
        "--resolv-conf=`"`""

$kubeletCommandLine = "$env:SYSTEMDRIVE\k\kubelet.exe " + ($args -join " ") + " $kubeAdmArgs"
Invoke-Expression $kubeletCommandLine
