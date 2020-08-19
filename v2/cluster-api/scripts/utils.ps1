$KUBERNETES_DIR = Join-Path $env:SystemDrive "k"
$CONTAINERD_DIR = Join-Path $env:SystemDrive "containerd"


function Start-ExternalCommand {
    Param(
        [Parameter(Mandatory=$true)]
        [Alias("Command")]
        [ScriptBlock]$ScriptBlock,
        [array]$ArgumentList=@(),
        [string]$ErrorMessage
    )
    if($LASTEXITCODE){
        # Leftover exit code. Some other process failed, and this
        # function was called before it was resolved.
        # There is no way to determine if the ScriptBlock contains
        # a powershell commandlet or a native application. So we clear out
        # the LASTEXITCODE variable before we execute. By this time, the value of
        # the variable is not to be trusted for error detection anyway.
        $LASTEXITCODE = ""
    }
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $res = Invoke-Command -ScriptBlock $ScriptBlock -ArgumentList $ArgumentList
    $ErrorActionPreference = $oldErrorActionPreference
    if ($LASTEXITCODE) {
        if(!$ErrorMessage){
            Throw ("Command exited with status: {0}" -f $LASTEXITCODE)
        }
        throw ("{0} (Exit code: $LASTEXITCODE)" -f $ErrorMessage)
    }
    return $res
}

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

function Get-ContainerRuntime {
    $dockerdBin = Get-Command "dockerd" -ErrorAction SilentlyContinue
    if($dockerdBin) {
        return "docker"
    }
    $containerd = Get-Command "containerd" -ErrorAction SilentlyContinue
    if($containerd) {
        return "containerd"
    }
    Throw "Could not find any container runtime installed"
}

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
    Start-ExternalCommand { PowerCfg.exe /S $guids[$PowerProfile] }
}
