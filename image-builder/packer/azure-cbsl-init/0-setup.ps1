$ErrorActionPreference = "Stop"

Import-Module KubernetesNodeSetup

Confirm-EnvVarsAreSet -EnvVars @("CONTAINER_RUNTIME", "INSTALL_LATEST_WINDOWS_UPDATES")
if([System.Convert]::ToBoolean($env:INSTALL_LATEST_WINDOWS_UPDATES)) {
    Install-LatestWindowsUpdates
}
Install-RequiredWindowsFeatures
if($env:CONTAINER_RUNTIME -eq "docker") {
    Install-PackageProvider -Name NuGet -Force -Confirm:$false
    Install-Module -Repository "PSGallery" -Name "DockerMsftProvider" -Force -Confirm:$false
    Install-Package -ProviderName "DockerMsftProvider" -Name "Docker" -Force -Confirm:$false
}
