Param(
    [parameter(Mandatory=$true)]
    [string]$CIVersion,
    [parameter(Mandatory=$true)]
    [string]$CIPackagesBaseURL
)

$ErrorActionPreference = "Stop"

$KUBERNETES_DIR = Join-Path $env:SystemDrive "k"
$CONTAINERD_DIR = Join-Path $env:SystemDrive "containerd"

curl.exe -s -o /tmp/utils.ps1 $CIPackagesBaseURL/scripts/utils.ps1
. /tmp/utils.ps1


function Stop-ContainerRuntime {
    switch (Get-ContainerRuntime) {
        "docker" {
            Stop-Service "docker"
        }
        "containerd" {
            Start-ExternalCommand { nssm stop containerd 2>$null }
        }
    }
}

function Start-ContainerRuntime {
    switch (Get-ContainerRuntime) {
        "docker" {
            Start-Service "docker"
        }
        "containerd" {
            Start-ExternalCommand { nssm start containerd 2>$null }
        }
    }
}

function Update-ContainerdBins {
    foreach($bin in @("containerd.exe", "containerd-shim-runhcs-v1.exe", "ctr.exe")) {
        Start-FileDownload "$CIPackagesBaseURL/containerd/bin/$bin" "$CONTAINERD_DIR\bin\$bin"
    }
    Start-FileDownload "$CIPackagesBaseURL/containerd/bin/crictl.exe" "$KUBERNETES_DIR\crictl.exe"
    Add-Content -Path "/tmp/kubeadm-join-config.yaml" -Encoding Ascii `
                -Value "  criSocket: ${env:CONTAINER_RUNTIME_ENDPOINT}"
}

function Wait-ReadyContainerd {
    Start-ExecuteWithRetry -ScriptBlock {
        $crictlInfo = Start-ExternalCommand { crictl info 2>$null }
        if($LASTEXITCODE) {
            Throw "Failed to execute: crictl info"
        }
        $crictlInfo = $crictlInfo | ConvertFrom-Json
        $runtimeReady = $crictlInfo.status.conditions | Where-Object type -eq RuntimeReady
        if(!$runtimeReady.status) {
            Throw "The containerd runtime is not ready yet"
        }
        $networkReady = $crictlInfo.status.conditions | Where-Object type -eq NetworkReady
        if(!$networkReady.status) {
            Throw "The containerd network is not ready yet"
        }
    } -MaxRetryCount 30 -RetryInterval 10 -RetryMessage "Containerd is not ready yet"
}

Set-MpPreference -DisableRealtimeMonitoring $true

Start-ExternalCommand { nssm stop kubelet 2>$null }
Stop-ContainerRuntime

Start-FileDownload "$CIPackagesBaseURL/$CIVersion/bin/windows/amd64/kubelet.exe" "$KUBERNETES_DIR\kubelet.exe"
Start-FileDownload "$CIPackagesBaseURL/$CIVersion/bin/windows/amd64/kubeadm.exe" "$KUBERNETES_DIR\kubeadm.exe"

$containerRuntime = Get-ContainerRuntime
switch ($containerRuntime) {
    "containerd" {
        Update-ContainerdBins
        Start-FileDownload "https://balutoiu.com/ionut/windows-container-networking/sdnoverlay.exe" `
                           "$env:SystemDrive\opt\cni\bin\sdnoverlay.exe"
    }
    "docker" {
        Set-Content -Path "$env:ProgramData\docker\config\daemon.json" `
                    -Value '{ "bridge" : "none" }' -Encoding Ascii
        mkdir -force "$env:SystemDrive\opt\cni\bin"
        $cniVersion = "v0.8.6"
        Start-FileDownload "https://github.com/containernetworking/plugins/releases/download/${cniVersion}/cni-plugins-windows-amd64-${cniVersion}.tgz" `
                            "$env:TEMP\cni-plugins.tgz"
        tar -xf $env:TEMP\cni-plugins.tgz -C "$env:SystemDrive\opt\cni\bin"
        if($LASTEXITCODE) {
            Throw "Failed to extract cni-plugins.tgz"
        }
        Remove-Item -Force $env:TEMP\cni-plugins.tgz
    }
}

Get-HnsNetwork | Remove-HnsNetwork
Get-NetAdapter -Physical | Rename-NetAdapter -NewName "Ethernet"

Start-ContainerRuntime
Start-ExternalCommand { nssm start kubelet 2>$null }

if($containerRuntime -eq "containerd") {
    Wait-ReadyContainerd
}

mkdir -Force C:\var\lib\kubelet\etc\kubernetes\manifests
