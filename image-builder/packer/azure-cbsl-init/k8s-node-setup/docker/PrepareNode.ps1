Param(
    [string]$KubernetesVersion="v1.22.0",
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
    docker login "${AcrName}.azurecr.io" -u "${AcrName}" -p "${AcrUserPassword}"
    if($LASTEXITCODE) {
        Throw "Failed to login to login to registry ${AcrName}.azurecr.io"
    }
    $images = Get-ContainerImages -ContainerRegistry "${AcrName}.azurecr.io" -KubernetesVersion $KubernetesVersion
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
Set-DockerConfig
Install-Kubelet -KubernetesVersion $KubernetesVersion `
                -StartKubeletScriptPath "$PSScriptRoot\..\start-kubelet.ps1" `
                -ContainerRuntimeServiceName "docker"
Install-ContainerNetworkingPlugins
Start-ContainerImagesPull

Stop-Service "Docker"
$hnsNetworks = Get-HnsNetwork
if($hnsNetworks) {
    $hnsNetworks | Remove-HnsNetwork
}
