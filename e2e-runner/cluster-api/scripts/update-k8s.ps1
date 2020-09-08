Param(
    [parameter(Mandatory=$true)]
    [string]$CIPackagesBaseURL,
    [parameter(Mandatory=$true)]
    [string]$CIVersion
)

$ErrorActionPreference = "Stop"

curl.exe -s -o /tmp/utils.ps1 $CIPackagesBaseURL/scripts/utils.ps1
. /tmp/utils.ps1


$binaries = @("kubelet.exe", "kubeadm.exe")
foreach($bin in $binaries) {
    Start-FileDownload "$CIPackagesBaseURL/$CIVersion/bin/windows/amd64/$bin" `
                       "$KUBERNETES_DIR\$bin"
}
