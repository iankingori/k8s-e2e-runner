$ErrorActionPreference = "Stop"

. "$PSScriptRoot\..\common.ps1"

$CLOUDBASE_INIT_INSTALLER_URL = "https://github.com/cloudbase/cloudbase-init/releases/download/1.1.2/CloudbaseInitSetup_1_1_2_x64.msi"


$cbslInitInstallerPath = Join-Path $env:TEMP "CloudbaseInitSetup_x64.msi"
Start-FileDownload -URL $CLOUDBASE_INIT_INSTALLER_URL -Destination $cbslInitInstallerPath

$p = Start-Process -Wait -PassThru -FilePath "msiexec.exe" -ArgumentList @("/i", $cbslInitInstallerPath, "/qn")
if ($p.ExitCode -ne 0) {
    Write-Log "Failed to install cloudbase-init"
}

Copy-Item -Path "$PSScriptRoot\cloudbase-init-unattended.conf" -Destination "$env:ProgramFiles\Cloudbase Solutions\Cloudbase-Init\conf\cloudbase-init-unattend.conf"
Copy-Item -Path "$PSScriptRoot\cloudbase-init.conf" -Destination "$env:ProgramFiles\Cloudbase Solutions\Cloudbase-Init\conf\cloudbase-init.conf"

Remove-Item -Force "$env:windir\Setup\Scripts\SetupComplete.cmd"
& "$env:ProgramFiles\Cloudbase Solutions\Cloudbase-Init\bin\SetSetupComplete.cmd"
if ($LASTEXITCODE) {
    Throw "Failed to run Cloudbase-Init\bin\SetSetupComplete.cmd"
}
