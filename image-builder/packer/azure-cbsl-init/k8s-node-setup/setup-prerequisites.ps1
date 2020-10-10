Param(
    [parameter(Mandatory=$true)]
    [string]$ContainerRuntime
)

$ErrorActionPreference = "Stop"


function Uninstall-Docker {
    $svc = Get-Service "Docker" -ErrorAction SilentlyContinue
    if(!$svc) {
        return
    }

    Write-Output "Running 'docker.exe system prune'"
    docker.exe system prune --all --volumes --force
    if($LASTEXITCODE) {
        Throw "Failed to run 'docker system prune'"
    }

    Write-Output "Uninstalling Docker"
    Stop-Service -Force "Docker"
    Uninstall-Package -Name "Docker" -ProviderName "DockerMsftProvider"
    Uninstall-Module -Name "DockerMsftProvider"

    $hnsNetworks = Get-HnsNetwork
    if($hnsNetworks) {
        $hnsNetworks | Remove-HnsNetwork
    }

    Remove-Item -Recurse -Force "${env:ProgramData}\docker"
}


if($ContainerRuntime -eq "containerd") {
    Uninstall-Docker
}
