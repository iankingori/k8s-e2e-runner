$ErrorActionPreference = "Stop"

. "$PSScriptRoot\common.ps1"

$extraUpdates = @{
    #
    # For each release, the array needs to have items given as:
    # @{
    #   "ID" = "KB4577069"
    #   "URL" = "http://download.windowsupdate.com/c/.../.../KB4577069.msu"
    # }
    #
    # NOTE: Only *.msu packages must be given.
    #
    "ltsc2019" = @()
    "1909" = @()
    "2004" = @()
}


Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
Install-Module -Name PSWindowsUpdate -Force -Confirm:$false

Start-ExecuteWithRetry {
    Install-WindowsUpdate -AcceptAll -IgnoreReboot
} -MaxRetryCount 10 -RetryInterval 30 -RetryMessage "Failed to install Windows updates"

$release = Get-WindowsRelease
foreach($update in $extraUpdates[$release]) {
    $hotfix = Get-HotFix -Id $update["ID"] -ErrorAction SilentlyContinue
    if($hotfix) {
        Write-Output "HotFix $($update["ID"]) is already installed"
        continue
    }
    $localPath = Join-Path $env:TEMP "$($update["ID"]).msu"
    Start-FileDownload $update["URL"] $localPath
    Write-Output "Installing $localPath"
    $p = Start-Process -Wait -PassThru -FilePath "wusa.exe" `
                       -ArgumentList @($localPath, "/quiet", "/norestart")
    switch($p.ExitCode) {
        0 {
            Write-Output "Succesfully installed $localPath"
        }
        3010 {
            Write-Output "Succesfully installed $localPath. Reboot required"
        }
        Default {
            Throw "Failed to install $localPath"
        }
    }
    $hotfix = Get-HotFix -Id $update["ID"] -ErrorAction SilentlyContinue
    if(!$hotfix) {
        Throw "Couldn't find $($update["ID"]) after finishing the wusa.exe installation"
    }
}
