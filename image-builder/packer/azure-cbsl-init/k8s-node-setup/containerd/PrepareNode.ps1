Param(
    [string]$KubernetesVersion="v1.21.1",
    [Parameter(Mandatory=$true)]
    [string]$AcrName,
    [Parameter(Mandatory=$true)]
    [string]$AcrUserName,
    [Parameter(Mandatory=$true)]
    [string]$AcrUserPassword
)

$ErrorActionPreference = "Stop"

. "$PSScriptRoot\..\common.ps1"


function Install-Containerd {
    mkdir -force $CONTAINERD_DIR
    mkdir -force $KUBERNETES_DIR
    mkdir -force $VAR_LOG_DIR
    mkdir -force "$ETC_DIR\cni\net.d"
    mkdir -force "$OPT_DIR\cni\bin"

    Start-FileDownload "https://github.com/containerd/containerd/releases/download/v${CRI_CONTAINERD_VERSION}/cri-containerd-cni-${CRI_CONTAINERD_VERSION}-windows-amd64.tar.gz" "$env:TEMP\cri-containerd-windows-amd64.tar.gz"
    tar xzf $env:TEMP\cri-containerd-windows-amd64.tar.gz -C $CONTAINERD_DIR
    if($LASTEXITCODE) {
        Throw "Failed to unzip containerd.zip"
    }
    Add-ToSystemPath $CONTAINERD_DIR
    Remove-Item -Force "$env:TEMP\cri-containerd-windows-amd64.tar.gz"

    Start-FileDownload "https://github.com/kubernetes-sigs/cri-tools/releases/download/v${CRICTL_VERSION}/crictl-v${CRICTL_VERSION}-windows-amd64.tar.gz" "$env:TEMP\crictl-windows-amd64.tar.gz"
    tar xzf $env:TEMP\crictl-windows-amd64.tar.gz -C $KUBERNETES_DIR
    if($LASTEXITCODE) {
        Throw "Failed to unzip crictl.zip"
    }
    Remove-Item -Force "$env:TEMP\crictl-windows-amd64.tar.gz"

    Copy-Item "$PSScriptRoot\nat.conf" "$ETC_DIR\cni\net.d\"
    foreach($cniBin in @("nat.exe", "sdnbridge.exe", "sdnoverlay.exe")) {
        Move-Item "$CONTAINERD_DIR\cni\$cniBin" "$OPT_DIR\cni\bin\"
    }
    Copy-Item "$PSScriptRoot\config.toml" "$CONTAINERD_DIR\config.toml"

    # TODO: Remove these binaries downloads, once those bundled with the stable package pass Windows conformance testing.
    Start-FileDownload "https://capzwin.blob.core.windows.net/bin/containerd-shim-runhcs-v1.exe" "$CONTAINERD_DIR\containerd-shim-runhcs-v1.exe"
    foreach($cniBin in @("nat.exe", "sdnbridge.exe", "sdnoverlay.exe")) {
        Start-FileDownload "https://capzwin.blob.core.windows.net/bin/$cniBin" "$OPT_DIR\cni\bin\$cniBin"
    }

    nssm install containerd $CONTAINERD_DIR\containerd.exe --config $CONTAINERD_DIR\config.toml
    if($LASTEXITCODE) {
        Throw "Failed to install containerd service"
    }
    nssm set containerd AppStdout $VAR_LOG_DIR\containerd.log
    if($LASTEXITCODE) {
        Throw "Failed to set AppStdout for containerd service"
    }
    nssm set containerd AppStderr $VAR_LOG_DIR\containerd.log
    if($LASTEXITCODE) {
        Throw "Failed to set AppStderr for containerd service"
    }

    nssm set containerd Start SERVICE_DEMAND_START
    if($LASTEXITCODE) {
        Throw "Failed to set containerd manual start type"
    }

    $env:CONTAINER_RUNTIME_ENDPOINT = "npipe:\\.\pipe\containerd-containerd"
    [Environment]::SetEnvironmentVariable("CONTAINER_RUNTIME_ENDPOINT", $env:CONTAINER_RUNTIME_ENDPOINT, [System.EnvironmentVariableTarget]::Machine)

    Start-Service -Name "containerd"
}

function Start-ContainerImagesPull {
    $images = Get-ContainerImages -ContainerRegistry "${AcrName}.azurecr.io" -KubernetesVersion $KubernetesVersion
    foreach($img in $images) {
        Start-ExecuteWithRetry {
            ctr.exe -n k8s.io image pull -u "${AcrUserName}:${AcrUserPassword}" $img
            if($LASTEXITCODE) {
                Throw "Failed to pull image: $img"
            }
        }
    }
}


Install-NSSM
Install-Containerd
Install-Kubelet -KubernetesVersion $KubernetesVersion `
                -StartKubeletScriptPath "$PSScriptRoot\..\StartKubelet.ps1" `
                -ContainerRuntimeServiceName "containerd"
Install-ContainerNetworkingPlugins
Start-ContainerImagesPull

nssm stop containerd
if($LASTEXITCODE) {
    Throw "Failed to stop containerd"
}
Remove-Item -Force "${VAR_LOG_DIR}\containerd.log"
$hnsNetworks = Get-HnsNetwork
if($hnsNetworks) {
    $hnsNetworks | Remove-HnsNetwork
}
