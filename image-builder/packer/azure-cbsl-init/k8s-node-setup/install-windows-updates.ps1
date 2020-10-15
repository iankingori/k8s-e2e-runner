$ErrorActionPreference = "Stop"

. "$PSScriptRoot\common.ps1"

$extraUpdates = @{
    "ltsc2019" = @(
        @{"ID" = "KB4577069"
          "URL" = "http://download.windowsupdate.com/d/msdownload/update/software/updt/2020/09/windows10.0-kb4577069-x64_ea0fa6bd418d0684a7a077cb62384ae593d43b7a.msu"}
    )
    "1909" = @(
        @{"ID" = "KB4577062"
          "URL" = "http://download.windowsupdate.com/d/msdownload/update/software/updt/2020/09/windows10.0-kb4577062-x64_fe452cf752c4368d5eeb07fa34bc05f1296b4be7.msu"}
    )
    "2004" = @(
        @{"ID" = "KB4577063"
          "URL" = "http://download.windowsupdate.com/c/msdownload/update/software/updt/2020/09/windows10.0-kb4577063-x64_3f928d263c1d36f690ece1edf1e2eb165a4b8fc5.msu"}
    )
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
