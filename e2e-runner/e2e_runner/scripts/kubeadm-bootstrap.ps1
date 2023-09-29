Param(
    [Parameter(Mandatory=$true)]
    [String]$CIPackagesBaseURL,
    [Switch]$K8sBins,
    [Switch]$ContainerdBins,
    [Switch]$ContainerdShimBins,
    [Switch]$CRIToolsBins,
    [Switch]$SDNCNIBins
)

$ErrorActionPreference = "Stop"

$global:BUILD_DIR = Join-Path $env:SystemDrive "build"
$global:KUBERNETES_DIR = Join-Path $env:SystemDrive "k"
$global:CONTAINERD_DIR = Join-Path $env:ProgramFiles "containerd"


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

function Add-ToServiceEnv {
    Param(
        [Parameter(Mandatory=$true)]
        [string]$ServiceName,
        [Parameter(Mandatory=$true)]
        [string]$Name,
        [Parameter(Mandatory=$true)]
        [string]$Value
    )
    $newEnv = @()
    $storedEnv = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName" -Name "Environment" -ErrorAction SilentlyContinue
    if($storedEnv) {
        $newEnv = $storedEnv.Environment.Split()
    }
    $newEnv += "${Name}=${Value}"
    $kwargs = @{
        Path = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
        Name = "Environment"
        Type = "MultiString"
        Value = $newEnv
    }
    if($storedEnv) {
        Set-ItemProperty @kwargs
    } else {
        New-ItemProperty @kwargs
    }
}

function Install-CIBinary {
    Param(
        [Parameter(Mandatory=$true)]
        [string]$URL,
        [Parameter(Mandatory=$true)]
        [string]$Destination
    )
    if(Test-Path $Destination) {
        Copy-Item -Force $Destination "${Destination}.bak"
    }
    Start-FileDownload $URL $Destination
}

function Set-ContainerdLogFile {
    Stop-Service -Force -Name containerd
    containerd.exe --unregister-service
    if($LASTEXITCODE) {
        Throw "Failed to unregister containerd service"
    }
    containerd.exe --register-service --log-level debug --log-file ${env:SystemDrive}\var\log\containerd.log
    if($LASTEXITCODE) {
        Throw "Failed to register containerd service"
    }
    Start-Service -Name containerd
}

function Update-Kubernetes {
    $binaries = @("kubelet.exe", "kubeadm.exe", "kubectl.exe")
    foreach($bin in $binaries) {
        Install-CIBinary "$CIPackagesBaseURL/kubernetes/bin/windows/amd64/$bin" "$KUBERNETES_DIR\$bin"
    }
    New-Item -ItemType Directory -Force -Path $BUILD_DIR
    Start-FileDownload "$CIPackagesBaseURL/kubernetes/bin/windows/amd64/kube-proxy.exe" "$BUILD_DIR\kube-proxy.exe"
}

function Update-Containerd {
    Stop-Service -Name "containerd" -Force
    $binaries = @(
        "containerd-stress.exe", "containerd.exe", "ctr.exe",
        "containerd-shim-runhcs-v1.exe",
        "crictl.exe", "critest.exe")
    foreach($bin in $binaries) {
        Install-CIBinary "$CIPackagesBaseURL/containerd/bin/$bin" "$CONTAINERD_DIR\$bin"
    }
    Add-ToServiceEnv -ServiceName "containerd" -Name "DISABLE_CRI_SANDBOXES" -Value "1"
    Start-Service -Name "containerd"
}

function Update-ContainerdShim {
    Install-CIBinary "$CIPackagesBaseURL/containerd-shim/bin/containerd-shim-runhcs-v1.exe" "$CONTAINERD_DIR\containerd-shim-runhcs-v1.exe"
}

function Update-CRITools {
    $binaries = @("crictl.exe", "critest.exe")
    foreach($bin in $binaries) {
        Install-CIBinary "$CIPackagesBaseURL/cri-tools/bin/$bin" "$CONTAINERD_DIR\$bin"
    }
}

function Update-SDNCNI {
    $binaries = @("nat.exe", "sdnbridge.exe", "sdnoverlay.exe")
    New-Item -ItemType Directory -Force -Path "${BUILD_DIR}\cni\bin"
    foreach($bin in $binaries) {
        Install-CIBinary "$CIPackagesBaseURL/cni/bin/$bin" "$BUILD_DIR\cni\bin\$bin"
    }
}


try {
    $svc = Get-Service -Name "containerd" -ErrorAction SilentlyContinue
    if($svc) {
        Set-ContainerdLogFile
    }

    if($K8sBins) {
        Update-Kubernetes
    }
    if($ContainerdBins) {
        Update-Containerd
    }
    if($ContainerdShimBins) {
        Update-ContainerdShim
    }
    if($CRIToolsBins) {
        Update-CRITools
    }
    if($SDNCNIBins) {
        Update-SDNCNI
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
