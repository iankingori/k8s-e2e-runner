$ErrorActionPreference = "Stop"

& "$env:SystemDrive\UnattendResources\CustomResources\docker\PrepareNode.ps1" -KubernetesVersion v1.19.0
if($LASTEXITCODE) {
    Throw "Failed to prepare the K8s node"
}
