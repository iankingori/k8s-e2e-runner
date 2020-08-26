$ErrorActionPreference = "Stop"

& "$env:SystemDrive\UnattendResources\CustomResources\docker\PrepareNode.ps1" -KubernetesVersion v1.18.8
if($LASTEXITCODE) {
    Throw "Failed to prepare the K8s node"
}
