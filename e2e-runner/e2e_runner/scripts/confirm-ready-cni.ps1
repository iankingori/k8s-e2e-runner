$ErrorActionPreference = "Stop"

$DOCKER_CNI_CONF_DIR = Join-Path $env:SystemDrive "etc\cni\net.d"
$CONTAINERD_CNI_CONF_DIR = Join-Path $env:SystemDrive "containerd\cni\conf"


function Get-FlannelCNIConf {
    foreach($dir in @($CONTAINERD_CNI_CONF_DIR, $DOCKER_CNI_CONF_DIR)) {
        if(Test-Path "${dir}\10-flannel.conf") {
            return "${dir}\10-flannel.conf"
        }
    }
}


$cniConf = Get-FlannelCNIConf
if(!$cniConf) {
    Write-Output $false
    exit 0
}

$networkName = (cat $cniConf | ConvertFrom-Json).Name
$hnsNetwork = Get-HnsNetwork | Where-Object Name -eq $networkName
if(!$hnsNetwork) {
    Write-Output $false
    exit 0
}

Write-Output $true
