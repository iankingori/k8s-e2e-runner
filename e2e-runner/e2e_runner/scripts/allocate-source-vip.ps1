$ErrorActionPreference = "Stop"

$KUBERNETES_DIR = Join-Path $env:SystemDrive "k"
$CNI_BIN_DIR = Join-Path $env:SystemDrive "opt\cni\bin"
$CNI_CONF_DIR = Join-Path $env:SystemDrive "etc\cni\net.d"
$SOURCE_VIP_FILE = Join-Path $KUBERNETES_DIR "sourceVip.json"


if(Test-Path $SOURCE_VIP_FILE) {
    Write-Output "The $SOURCE_VIP_FILE already exists"
    exit 0
}

if(!(Test-Path "$CNI_CONF_DIR\10-flannel.conf")) {
    Write-Output "The CNI config file doesn't exist"
    exit 1
}

$networkName = (cat "$CNI_CONF_DIR\10-flannel.conf" | ConvertFrom-Json).Name
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
$env:CNI_PATH = $CNI_BIN_DIR
Get-Content "$KUBERNETES_DIR\sourceVipRequest.json" | & "$env:CNI_PATH\host-local.exe" | Out-File $SOURCE_VIP_FILE -Encoding ascii
if($LASTEXITCODE) {
    Write-Output "Failed to allocate the source VIP"
    exit 1
}
