$ErrorActionPreference = "Stop"

Import-Module KubernetesNodeSetup

Confirm-EnvVarsAreSet -EnvVars @(
    "CONTAINER_RUNTIME",
    "INSTALL_LATEST_WINDOWS_UPDATES")

Get-NetAdapter -Physical | Rename-NetAdapter -NewName "packer"

if([System.Convert]::ToBoolean($env:INSTALL_LATEST_WINDOWS_UPDATES)) {
    Install-LatestWindowsUpdates
}
Install-RequiredWindowsFeatures

switch ($env:CONTAINER_RUNTIME) {
    "docker" {
        Install-Docker
    }
    "containerd" {
        Install-Containerd
    }
    default {
        Throw "Unsupported container runtime: ${env:CONTAINER_RUNTIME}"
    }
}
