Param(
    [Parameter(Mandatory=$true)]
    [String]$CIPackagesBaseURL,
    [Parameter(Mandatory=$true)]
    [String]$CIVersion,
    [Switch]$K8sBins,
    [Switch]$SDNCNIBins,
    [Switch]$ContainerdBins,
    [Switch]$ContainerdShimBins
)

$ErrorActionPreference = "Stop"

$global:BUILD_DIR = Join-Path $env:SystemDrive "build"
$global:KUBERNETES_DIR = Join-Path $env:SystemDrive "k"
$global:CONTAINERD_DIR = Join-Path $env:ProgramFiles "containerd"
$global:CRICTL_YAML = @"
runtime-endpoint: npipe:\\.\pipe\containerd-containerd
image-endpoint: npipe:\\.\pipe\containerd-containerd
"@
# https://github.com/kubernetes-sigs/cri-tools/releases
$global:CRICTL_VERSION = "v1.23.0"


function Start-ExecuteWithRetry {
    Param(
        [Parameter(Mandatory=$true)]
        [ScriptBlock]$ScriptBlock,
        [int]$MaxRetryCount=10,
        [int]$RetryInterval=3,
        [string]$RetryMessage,
        [array]$ArgumentList=@()
    )
    $currentErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $retryCount = 0
    while ($true) {
        Write-Output "Start-ExecuteWithRetry attempt $retryCount"
        try {
            $res = Invoke-Command -ScriptBlock $ScriptBlock `
                                  -ArgumentList $ArgumentList
            $ErrorActionPreference = $currentErrorActionPreference
            Write-Output "Start-ExecuteWithRetry terminated"
            return $res
        } catch [System.Exception] {
            $retryCount++
            if ($retryCount -gt $MaxRetryCount) {
                $ErrorActionPreference = $currentErrorActionPreference
                Write-Output "Start-ExecuteWithRetry exception thrown"
                throw
            } else {
                if($RetryMessage) {
                    Write-Output "Start-ExecuteWithRetry RetryMessage: $RetryMessage"
                } elseif($_) {
                    Write-Output "Start-ExecuteWithRetry Retry: $_.ToString()"
                }
                Start-Sleep $RetryInterval
            }
        }
    }
}

function Start-FileDownload {
    Param(
        [Parameter(Mandatory=$true)]
        [string]$URL,
        [Parameter(Mandatory=$true)]
        [string]$Destination,
        [Parameter(Mandatory=$false)]
        [int]$RetryCount=10
    )
    if(Test-Path $Destination) {
        Remove-Item -Force $Destination
    }
    Start-ExecuteWithRetry -ScriptBlock {
        curl.exe -C - -L -s -o $Destination $URL
        if($LASTEXITCODE) {
            Throw "Failed to download $URL"
        }
    } -MaxRetryCount $RetryCount -RetryInterval 3 -RetryMessage "Failed to download $URL. Retrying"
}

function Set-PowerProfile {
    Param(
        [Parameter(Mandatory=$true)]
        [ValidateSet("PowerSave", "Balanced", "Performance")]
        [string]$PowerProfile
    )
    $guids = @{
        "PowerSave" = "a1841308-3541-4fab-bc81-f71556f20b4a";
        "Balanced" = "381b4222-f694-41f0-9685-ff5bb260df2e";
        "Performance" = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c";
    }
    PowerCfg.exe /S $guids[$PowerProfile]
    if($LASTEXITCODE) {
        Throw "Failed to set power profile to $PowerProfile"
    }
}

function Install-Crictl {
    Start-FileDownload "https://github.com/kubernetes-sigs/cri-tools/releases/download/${CRICTL_VERSION}/crictl-${CRICTL_VERSION}-windows-amd64.tar.gz" "$env:TEMP\crictl-windows-amd64.tar.gz"
    tar xzf $env:TEMP\crictl-windows-amd64.tar.gz -C $CONTAINERD_DIR
    if($LASTEXITCODE) {
        Throw "Failed to unzip crictl.zip"
    }
    Remove-Item -Force "$env:TEMP\crictl-windows-amd64.tar.gz"
    New-Item -ItemType Directory -Force -Path "${env:SystemDrive}\Users\capi\.crictl"
    $global:CRICTL_YAML | Out-File -FilePath "${env:SystemDrive}\Users\capi\.crictl\crictl.yaml" -Encoding ascii
}

function Update-Kubernetes {
    $binaries = @("kubelet.exe", "kubeadm.exe", "kubectl.exe")
    foreach($bin in $binaries) {
        Start-FileDownload "$CIPackagesBaseURL/$CIVersion/bin/windows/amd64/$bin" "$KUBERNETES_DIR\$bin"
    }
    Start-FileDownload "$CIPackagesBaseURL/scripts/kubelet-start.ps1" "$KUBERNETES_DIR\StartKubelet.ps1"
}

function Update-SDNCNI {
    $binaries = @("nat.exe", "sdnbridge.exe", "sdnoverlay.exe")
    New-Item -ItemType Directory -Force -Path "${BUILD_DIR}\cni\bin"
    foreach($bin in $binaries) {
        Start-FileDownload "$CIPackagesBaseURL/cni/$bin" "$BUILD_DIR\cni\bin\$bin"
    }
}

function Update-Containerd {
    Stop-Service -Name "containerd" -Force
    $binaries = @("containerd-stress.exe", "containerd.exe", "ctr.exe", "crictl.exe")
    foreach($bin in $binaries) {
        Start-FileDownload "$CIPackagesBaseURL/containerd/bin/$bin" "$CONTAINERD_DIR\$bin"
    }
    Start-Service -Name "containerd"
}

function Update-ContainerdShim {
    Start-FileDownload "$CIPackagesBaseURL/containerd/bin/containerd-shim-runhcs-v1.exe" "$CONTAINERD_DIR\containerd-shim-runhcs-v1.exe"
}


try {
    if($K8sBins) {
        Update-Kubernetes
    }
    if($SDNCNIBins) {
        Update-SDNCNI
    }
    if($ContainerdBins) {
        Update-Containerd
    }
    if($ContainerdShimBins) {
        Update-ContainerdShim
    }

    # Rename main adapter NIC
    $adapter = Get-NetAdapter -Name "Ethernet 2" -ErrorAction SilentlyContinue
    if($adapter) {
        $adapter | Rename-NetAdapter -NewName "eth0"
    }

    # Disable Windows Updates service
    Set-Service -Name "wuauserv" -StartupType Disabled
    Stop-Service -Name "wuauserv"

    # Disable Windows Defender
    Set-MpPreference -DisableRealtimeMonitoring $true

    # Set 'Performance' power profile
    Set-PowerProfile -PowerProfile "Performance"

    $svc = Get-Service -Name "containerd" -ErrorAction SilentlyContinue
    if($svc) {
        Install-Crictl
    }

    nssm set kubelet Start SERVICE_AUTO_START
    if($LASTEXITCODE) {
        Throw "Failed to set kubelet automatic startup type"
    }
} catch [System.Exception] {
    # If errors happen, uninstall the kubelet. This will render the machine
    # not started, and fail the job.
    nssm stop kubelet
    nssm remove kubelet confirm
    Throw $_
}
