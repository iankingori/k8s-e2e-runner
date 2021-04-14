Param(
    [string]$KubernetesVersion="v1.21.0",
    [Parameter(Mandatory=$true)]
    [string]$AcrName,
    [Parameter(Mandatory=$true)]
    [string]$AcrUserName,
    [Parameter(Mandatory=$true)]
    [string]$AcrUserPassword
)

$ErrorActionPreference = "Stop"

. "$PSScriptRoot\..\common.ps1"


function Set-DockerConfig {
    Set-Content -Path "$env:ProgramData\docker\config\daemon.json" `
                -Value '{ "bridge" : "none" }' -Encoding Ascii

    Set-Service -Name "docker" -StartupType Manual
}

function Start-ContainerImagesPull {
    $windowsRelease = Get-WindowsRelease
    $images = @(
        (Get-KubernetesPauseImage),
        (Get-NanoServerImage),
        "mcr.microsoft.com/windows/servercore:${windowsRelease}",
        "${AcrName}.azurecr.io/flannel-windows:v${FLANNEL_VERSION}-windowsservercore-${windowsRelease}",
        "${AcrName}.azurecr.io/kube-proxy-windows:${KubernetesVersion}-windowsservercore-${windowsRelease}"
    )
    docker login "${AcrName}.azurecr.io" -u "${AcrName}" -p "${AcrUserPassword}"
    if($LASTEXITCODE) {
        Throw "Failed to login to login to registry ${AcrName}.azurecr.io"
    }
    foreach($img in $images) {
        Start-ExecuteWithRetry {
            docker.exe image pull $img
            if($LASTEXITCODE) {
                Throw "Failed to pull image: $img"
            }
        }
    }
    docker logout "${AcrName}.azurecr.io"
    if($LASTEXITCODE) {
        Throw "Failed to login from registry ${AcrName}.azurecr.io"
    }
}


Install-NSSM
Install-CNI
Set-DockerConfig
Install-Kubelet -KubernetesVersion $KubernetesVersion `
                -StartKubeletScriptPath "$PSScriptRoot\StartKubelet.ps1" `
                -ContainerRuntimeServiceName "docker"
Start-ContainerImagesPull

Stop-Service "Docker"
$hnsNetworks = Get-HnsNetwork
if($hnsNetworks) {
    $hnsNetworks | Remove-HnsNetwork
}