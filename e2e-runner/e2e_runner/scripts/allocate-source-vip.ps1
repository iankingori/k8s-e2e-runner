$ErrorActionPreference = "Stop"

$KUBERNETES_DIR = Join-Path $env:SystemDrive "k"
$SOURCE_VIP_FILE = Join-Path $KUBERNETES_DIR "sourceVip.json"

$DOCKER_CNI_BIN_DIR = Join-Path $env:SystemDrive "opt\cni\bin"
$CONTAINERD_CNI_BIN_DIR = Join-Path $env:SystemDrive "containerd\cni\bin"

$DOCKER_CNI_CONF_DIR = Join-Path $env:SystemDrive "etc\cni\net.d"
$CONTAINERD_CNI_CONF_DIR = Join-Path $env:SystemDrive "containerd\cni\conf"


function Get-FlannelCNIConf {
    foreach($dir in @($CONTAINERD_CNI_CONF_DIR, $DOCKER_CNI_CONF_DIR)) {
        if(Test-Path "${dir}\10-flannel.conf") {
            return "${dir}\10-flannel.conf"
        }
    }
}

function Get-CNIBinDir {
    if(Test-Path $CONTAINERD_CNI_BIN_DIR) {
        return $CONTAINERD_CNI_BIN_DIR
    }
    if(Test-Path $DOCKER_CNI_BIN_DIR) {
        return $DOCKER_CNI_BIN_DIR
    }
}


if(Test-Path $SOURCE_VIP_FILE) {
    Write-Output "The $SOURCE_VIP_FILE already exists"
    exit 0
}

$cniConf = Get-FlannelCNIConf
if(!$cniConf) {
    Write-Output "The CNI config file doesn't exist"
    exit 1
}

$cniBinDir = Get-CNIBinDir
if(!$cniBinDir) {
    Write-Output "The CNI bin directory doesn't exist"
    exit 1
}

$networkName = (cat $cniConf | ConvertFrom-Json).Name
$hnsNetwork = Get-HnsNetwork | Where-Object Name -eq $networkName
if(!$hnsNetwork) {
    Write-Output "The HNS network $networkName doesn't exist"
    exit 1
}

$subnet = $hnsNetwork.Subnets[0].AddressPrefix
$ipamConfig = @"
{"cniVersion": "0.2.0", "name": "$networkName", "ipam":{"type":"host-local","ranges":[[{"subnet":"$subnet"}]],"dataDir":"/var/lib/cni/networks"}}
"@
Set-Content -Path "$KUBERNETES_DIR\sourceVipRequest.json" -Value $ipamConfig -Encoding ascii

$env:CNI_COMMAND = "ADD"
$env:CNI_CONTAINERID = "dummy"
$env:CNI_NETNS = "dummy"
$env:CNI_IFNAME = "dummy"
$env:CNI_PATH = $cniBinDir
Get-Content "$KUBERNETES_DIR\sourceVipRequest.json" | & "$env:CNI_PATH\host-local.exe" | Out-File $SOURCE_VIP_FILE -Encoding ascii
if($LASTEXITCODE) {
    Write-Output "Failed to allocate the source VIP"
    if(Test-Path $SOURCE_VIP_FILE) {
        Remove-Item -Force $SOURCE_VIP_FILE
    }
    exit 1
}
