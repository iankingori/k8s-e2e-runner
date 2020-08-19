Param(
    [parameter(Mandatory=$true)]
    [string]$CIPackagesBaseURL
)

$ErrorActionPreference = "Stop"

curl.exe -s -o /tmp/utils.ps1 $CIPackagesBaseURL/scripts/utils.ps1
. /tmp/utils.ps1


$binaries = @("containerd.exe", "containerd-shim-runhcs-v1.exe", "ctr.exe", "crictl.exe")
foreach($bin in $binaries) {
    Start-FileDownload "$CIPackagesBaseURL/containerd/bin/$bin" "$CONTAINERD_DIR\bin\$bin"
}
Add-Content -Path "/tmp/kubeadm-join-config.yaml" -Encoding Ascii `
            -Value "  criSocket: ${env:CONTAINER_RUNTIME_ENDPOINT}"
