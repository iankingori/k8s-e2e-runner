Param(
    [ValidateSet("docker", "containerd")]
    [string]$ContainerRuntime
)

$ErrorActionPreference = "Stop"

. "$PSScriptRoot\common.ps1"


Start-ExecuteWithRetry `
    -ScriptBlock { Install-WindowsFeature -Name "Containers" -Confirm:$false } `
    -MaxRetryCount 10 -RetryInterval 30 -RetryMessage "Failed to install 'Containers' Windows feature"

if($ContainerRuntime -eq "docker") {
    Install-PackageProvider -Name NuGet -Force -Confirm:$false
    Install-Module -Repository "PSGallery" -Name "DockerMsftProvider" -Force -Confirm:$false
    Install-Package -ProviderName "DockerMsftProvider" -Name "Docker" -Force -Confirm:$false
}
