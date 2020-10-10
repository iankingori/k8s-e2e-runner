Param(
    [parameter(Mandatory=$true)]
    [string]$KubernetesVersion
)

$ErrorActionPreference = "Stop"

. "$PSScriptRoot\..\common.ps1"


function Set-DockerConfig {
    Set-Content -Path "$env:ProgramData\docker\config\daemon.json" `
                -Value '{ "bridge" : "none" }' -Encoding Ascii

    Set-Service -Name "docker" -StartupType Manual
}

function Start-ContainerImagesPull {
    $windowsRelease = Get-WindowsRelease
    $images = @(
        (Get-KubernetesPauseImage),
        (Get-NanoServerImage),
        "mcr.microsoft.com/windows/servercore:${windowsRelease}",
        "e2eteam/flannel-windows:v0.13.0-rc1-windowsservercore-${windowsRelease}",
        "e2eteam/kube-proxy-windows:${KubernetesVersion}-windowsservercore-${windowsRelease}",
        "e2eteam/busybox:1.29",
        "e2eteam/curl:1803",
        "e2eteam/java:openjdk-8-jre",
        "e2eteam/test-webserver:1.0",
        "e2eteam/cassandra:v13",
        "e2eteam/dnsutils:1.1",
        "e2eteam/echoserver:2.2",
        "e2eteam/entrypoint-tester:1.0",
        "e2eteam/etcd:v3.3.10",
        "e2eteam/etcd:3.3.10",
        "e2eteam/fakegitserver:1.0",
        "e2eteam/gb-frontend:v6",
        "e2eteam/gb-redisslave:v3",
        "e2eteam/hazelcast-kubernetes:3.8_1",
        "e2eteam/hostexec:1.1",
        "e2eteam/iperf:1.0",
        "e2eteam/jessie-dnsutils:1.0",
        "e2eteam/kitten:1.0",
        "e2eteam/liveness:1.1",
        "e2eteam/logs-generator:1.0",
        "e2eteam/mounttest:1.0",
        "e2eteam/nautilus:1.0",
        "e2eteam/net:1.0",
        "e2eteam/netexec:1.1",
        "e2eteam/nettest:1.0",
        "e2eteam/nginx:1.14-alpine",
        "e2eteam/nginx:1.15-alpine",
        "e2eteam/no-snat-test:1.0",
        "e2eteam/pause:3.1",
        "e2eteam/port-forward-tester:1.0",
        "e2eteam/porter:1.0",
        "e2eteam/redis:1.0",
        "e2eteam/resource-consumer:1.4",
        "e2eteam/resource-consumer:1.5",
        "e2eteam/resource-consumer-controller:1.0",
        "e2eteam/rethinkdb:1.16.0_1",
        "e2eteam/sample-apiserver:1.10",
        "e2eteam/serve-hostname:1.1",
        "e2eteam/webhook:1.13v1"
    )
    foreach($img in $images) {
        Start-ExecuteWithRetry {
            docker.exe image pull $img
            if($LASTEXITCODE) {
                Throw "Failed to pull image: $img"
            }
        }
    }
}


Install-NSSM
Install-CNI
Set-DockerConfig
Install-Kubelet -KubernetesVersion $KubernetesVersion `
                -StartKubeletScriptPath "$PSScriptRoot\StartKubelet.ps1" `
                -ContainerRuntimeServiceName "docker"
Start-ContainerImagesPull

Stop-Service "Docker"
$hnsNetworks = Get-HnsNetwork
if($hnsNetworks) {
    $hnsNetworks | Remove-HnsNetwork
}