Param(
    [parameter(Mandatory=$true)]
    [string]$CIPackagesBaseURL
)

$ErrorActionPreference = "Stop"

curl.exe -s -o /tmp/utils.ps1 $CIPackagesBaseURL/scripts/utils.ps1
. /tmp/utils.ps1


$binaries = @("nat.exe", "sdnbridge.exe", "sdnoverlay.exe")
foreach($bin in $binaries) {
    Start-FileDownload "$CIPackagesBaseURL/cni/$bin" "$OPT_DIR\cni\bin\$bin"
}
