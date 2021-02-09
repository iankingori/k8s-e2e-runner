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
        "${env:ACR_NAME}.azurecr.io/flannel-windows:v0.13.0-windowsservercore-${windowsRelease}",
        "${env:ACR_NAME}.azurecr.io/kube-proxy-windows:${env:KUBERNETES_VERSION}-windowsservercore-${windowsRelease}"
    )
    docker login "${env:ACR_NAME}.azurecr.io" -u "${env:ACR_USER_NAME}" -p "${env:ACR_USER_PASSWORD}"
    if($LASTEXITCODE) {
        Throw "Failed to login to login to registry ${env:ACR_NAME}.azurecr.io"
    }
    foreach($img in $images) {
        Start-ExecuteWithRetry {
            docker.exe image pull $img
            if($LASTEXITCODE) {
                Throw "Failed to pull image: $img"
            }
        }
    }
    docker logout "${env:ACR_NAME}.azurecr.io"
    if($LASTEXITCODE) {
        Throw "Failed to login from registry ${env:ACR_NAME}.azurecr.io"
    }
}


Install-NSSM
Install-CNI
Set-DockerConfig
Install-Kubelet -KubernetesVersion $env:KUBERNETES_VERSION `
                -StartKubeletScriptPath "$PSScriptRoot\StartKubelet.ps1" `
                -ContainerRuntimeServiceName "docker"
Start-ContainerImagesPull

Stop-Service "Docker"
$hnsNetworks = Get-HnsNetwork
if($hnsNetworks) {
    $hnsNetworks | Remove-HnsNetwork
}