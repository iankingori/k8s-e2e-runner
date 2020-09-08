$ErrorActionPreference = "Stop"

$CNI_CONF_DIR = Join-Path $env:SystemDrive "etc\cni\net.d"


if(!(Test-Path "$CNI_CONF_DIR\10-flannel.conf")) {
    Write-Output $false
    exit 0
}

$networkName = (cat "$CNI_CONF_DIR\10-flannel.conf" | ConvertFrom-Json).Name
$hnsNetwork = Get-HnsNetwork | Where-Object Name -eq $networkName
if(!$hnsNetwork) {
    Write-Output $false
    exit 0
}

Write-Output $true
