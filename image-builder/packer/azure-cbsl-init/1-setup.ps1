$ErrorActionPreference = "Stop"

Import-Module KubernetesNodeSetup

Confirm-EnvVarsAreSet -EnvVars @(
    "CONTAINER_RUNTIME",
    "ACR_NAME",
    "ACR_USER_NAME",
    "ACR_USER_PASSWORD",
    "KUBERNETES_VERSION")

switch ($env:CONTAINER_RUNTIME) {
    "docker" {
        Install-DockerKubernetesNode
    }
    "containerd" {
        Install-ContainerdKubernetesNode
    }
    default {
        Throw "Unsupported container runtime: ${env:CONTAINER_RUNTIME}"
    }
}

Install-Wins
Install-OpenSSHServer
Install-CloudbaseInit
Get-WindowsBuildInfo
