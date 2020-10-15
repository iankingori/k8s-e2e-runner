Param(
    [parameter(Mandatory=$true)]
    [string]$CIPackagesBaseURL
)

$ErrorActionPreference = "Stop"

curl.exe -s -o /tmp/utils.ps1 $CIPackagesBaseURL/scripts/utils.ps1
. /tmp/utils.ps1


Set-Service -Name "wuauserv" -StartupType Disabled
Stop-Service -Name "wuauserv"
Set-MpPreference -DisableRealtimeMonitoring $true
Set-PowerProfile -PowerProfile "Performance"
Get-NetAdapter -Physical | Rename-NetAdapter -NewName "eth0"

switch(Get-ContainerRuntime) {
    "docker" {
        Set-Service -Name "docker" -StartupType Automatic
        Start-Service -Name "docker"
    }
    "containerd" {
        Add-Content -Path "/tmp/kubeadm-join-config.yaml" -Encoding Ascii `
                    -Value "  criSocket: ${env:CONTAINER_RUNTIME_ENDPOINT}"
        Start-ExternalCommand { nssm set containerd Start SERVICE_AUTO_START 2>$null }
        Start-ExternalCommand { nssm start containerd 2>$null }
        Wait-ReadyContainerd
    }
}

Start-ExternalCommand { nssm set kubelet Start SERVICE_AUTO_START 2>$null }
