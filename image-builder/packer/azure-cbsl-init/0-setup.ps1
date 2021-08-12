$ErrorActionPreference = "Stop"

Import-Module KubernetesNodeSetup

Confirm-EnvVarsAreSet -EnvVars @("CONTAINER_RUNTIME")
Install-LatestWindowsUpdates
Install-RequiredWindowsFeatures
if($env:CONTAINER_RUNTIME -eq "docker") {
    Install-PackageProvider -Name NuGet -Force -Confirm:$false
    Install-Module -Repository "PSGallery" -Name "DockerMsftProvider" -Force -Confirm:$false
    Install-Package -ProviderName "DockerMsftProvider" -Name "Docker" -Force -Confirm:$false
}
