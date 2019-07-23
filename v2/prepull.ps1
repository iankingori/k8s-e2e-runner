# Script file to create tmp directory in windows nodes

param (
    [ValidateSet("docker","containerd")][string]$runtime = "docker"
)

mkdir c:\tmp

# ( atuvenie ) This is hacky and ugly and horrible and should in no way remain here. Temp until fix in ansible.
if ( $runtime -eq "containerd") {
    wget "https://www.dropbox.com/s/8d93vkszcgja493/containerd-shim-runhcs-v1.exe?dl=1" -OutFile c:\k\containerd-shim-runhcs-v1.exe
}

$pullCmd = "docker pull"
if ( $runtime -eq "containerd") {
    $pullCmd = "c:\k\ctr.exe --namespace k8s.io image pull"
}

Write-Host "Disable monitoring"
Set-MpPreference -DisableRealtimeMonitoring $true

Write-Host "Prepulling all test images"

iex "$pullCmd docker.io/e2eteam/busybox:1.29"
iex "$pullCmd docker.io/e2eteam/agnhost:2.4"
iex "$pullCmd docker.io/e2eteam/redis:5.0.5-alpine"
iex "$pullCmd gcr.io/authenticated-image-pulling/windows-nanoserver:v1"

# Resize partition to 100GB as vm image has only 30GB

Write-Host "Resizing partition"

$MaxSize = (Get-PartitionSupportedSize -DriveLetter "c").sizeMax
Resize-Partition -DriveLetter "c" -Size $MaxSize

[System.Environment]::SetEnvironmentVariable('DOCKER_API_VERSION', "1.39", [System.EnvironmentVariableTarget]::Machine)
