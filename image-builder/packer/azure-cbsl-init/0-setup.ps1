$ErrorActionPreference = "Stop"

Import-Module KubernetesNodeSetup

Confirm-EnvVarsAreSet -EnvVars @(
    "CONTAINER_RUNTIME",
    "WU_INSTALL_LATEST")

Get-NetAdapter -Physical | Rename-NetAdapter -NewName "packer"

Get-WindowsBuildInfo
if([System.Convert]::ToBoolean($env:WU_INSTALL_LATEST)) {
    Install-WindowsUpdates
}
if($env:WU_INSTALL_KB_IDS) {
    Install-WindowsUpdates -KBArticleID ($env:WU_INSTALL_KB_IDS -split ",")
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
