
# Return codes:
#  0 - success
#  1 - install failure
#  2 - download failure
#  3 - unrecognized patch extension

Param(
    [string[]]$URIs
)

$ErrorActionPreference = "Stop"


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


foreach($uri in $URIs) {
    Write-Host "Processing $uri"
    $pathOnly = $uri
    if ($pathOnly.Contains("?")) {
        $pathOnly = $pathOnly.Split("?")[0]
    }
    $fileName = Split-Path $pathOnly -Leaf
    $ext = [io.path]::GetExtension($fileName)
    $fullName = [io.path]::Combine($env:TEMP, $fileName)
    Start-FileDownload -URL $uri -Destination $fullName
    switch ($ext) {
        ".exe" {
            Start-Process -FilePath bcdedit.exe -ArgumentList "/set {current} testsigning on" -Wait
            Write-Host "Starting $fullName"
            $proc = Start-Process -Passthru -Wait -FilePath "$fullName" -ArgumentList "/q /norestart"
        }
        ".msu" {
            Write-Host "Installing $fullName"
            $proc = Start-Process -Passthru -Wait -FilePath wusa.exe -ArgumentList "$fullName /quiet /norestart"
        }
        ".cab" {
            Write-Host "Installing $fullName"
            $proc = Start-Process -Passthru -Wait -FilePath DISM.exe -ArgumentList "/Online /Add-Package /PackagePath:$fullName /Quiet /NoRestart"
        }
        Default {
            Write-Error "This script extension doesn't know how to install $ext files"
            exit 3
        }
    }

    switch ($proc.ExitCode) {
        0 {
            Write-Host "Finished running $fullName"
        }
        3010 {
            Write-Host "Finished running $fullName. Reboot required to finish patching."
        }
        Default {
            Write-Error "Error running $fullName, exitcode $($proc.ExitCode)"
            exit 1
        }
    }
}

# No failures, reboot now
Restart-Computer -Force
