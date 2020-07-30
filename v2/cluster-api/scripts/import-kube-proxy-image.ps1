Param(
    [parameter(Mandatory=$true)]
    [string]$CIVersion,
    [parameter(Mandatory=$true)]
    [string]$CIPackagesBaseURL
)

$ErrorActionPreference = "Stop"

curl.exe -s -o /tmp/utils.ps1 $CIPackagesBaseURL/scripts/utils.ps1
. /tmp/utils.ps1


function Import-KubeProxyImage {
    Start-FileDownload "$CIPackagesBaseURL/$CIVersion/images/kube-proxy-windows.tar" "/tmp/kube-proxy-windows.tar"
    Write-Output "Importing kube-proxy container image"
    switch (Get-ContainerRuntime) {
        "docker" {
            Start-ExternalCommand { docker.exe image load -i /tmp/kube-proxy-windows.tar 2>$null }
        }
        "containerd" {
            Start-ExternalCommand { ctr.exe -n k8s.io image import /tmp/kube-proxy-windows.tar 2>$null }
        }
    }
    Write-Output "Finished importing kube-proxy container image"
    Remove-Item "/tmp/kube-proxy-windows.tar"
}

Import-KubeProxyImage
