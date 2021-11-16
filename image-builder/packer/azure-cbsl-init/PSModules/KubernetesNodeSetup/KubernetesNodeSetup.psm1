$ErrorActionPreference = "Stop"

$global:CONTAINERD_DIR = Join-Path $env:SystemDrive "containerd"
$global:TMP_DIR = Join-Path $env:SystemDrive "tmp"

# https://github.com/containerd/containerd/releases
$global:CRI_CONTAINERD_VERSION = "v1.6.0-beta.1"
# https://github.com/kubernetes-sigs/cri-tools/releases
$global:CRICTL_VERSION = "v1.22.0"
# https://github.com/rancher/wins/releases
$global:WINS_VERSION = "v0.1.1"


function Install-WindowsUpdates {
    Param(
        [String[]]$KBArticleID
    )
    Write-Output "Installing PSWindowsUpdate PowerShell module"
    Install-PackageProvider -Name "NuGet" -Force -Confirm:$false
    Set-PSRepository -Name "PSGallery" -InstallationPolicy Trusted
    Install-Module -Name "PSWindowsUpdate" -Force -Confirm:$false

    Write-Output "Installing Windows updates"
    if($KBArticleID) {
        Write-Output "Installing Windows updates: $KBArticleID"
    } else {
        Write-Output "Installing latest Windows updates"
    }
    Start-ExecuteWithRetry `
        -ScriptBlock {
            Param(
                [String[]]$KBArticleID
            )
            $params = @{
                "AcceptAll" = $true
                "IgnoreReboot" = $true
            }
            if($KBArticleID) {
                $params["KBArticleID"] = $KBArticleID
            }
            Install-WindowsUpdate @params
        } `
        -ArgumentList @($KBArticleID) `
        -MaxRetryCount 10 `
        -RetryInterval 30 `
        -RetryMessage "Failed to install Windows updates. Retrying"
}

function Install-RequiredWindowsFeatures {
    Start-ExecuteWithRetry `
        -ScriptBlock { Install-WindowsFeature -Name "Containers" -Confirm:$false } `
        -MaxRetryCount 10 -RetryInterval 30 `
        -RetryMessage "Failed to install 'Containers' Windows feature"
}

function Install-CloudbaseInit {
    Write-Output "Downloading cloudbase-init"
    $cbslInitInstallerPath = Join-Path $env:TEMP "CloudbaseInitSetup_x64.msi"
    Start-FileDownload `
        -URL "https://github.com/cloudbase/cloudbase-init/releases/download/1.1.2/CloudbaseInitSetup_1_1_2_x64.msi" `
        -Destination $cbslInitInstallerPath

    Write-Output "Installing cloudbase-init"
    $p = Start-Process -Wait -PassThru -FilePath "msiexec.exe" -ArgumentList @("/i", $cbslInitInstallerPath, "/qn")
    if ($p.ExitCode -ne 0) {
        Throw "Failed to install cloudbase-init"
    }

    Write-Output "Copying the cloudbase-init conf files"
    Copy-Item -Path "$PSScriptRoot\cloudbase-init\cloudbase-init-unattended.conf" -Destination "$env:ProgramFiles\Cloudbase Solutions\Cloudbase-Init\conf\cloudbase-init-unattend.conf"
    Copy-Item -Path "$PSScriptRoot\cloudbase-init\cloudbase-init.conf" -Destination "$env:ProgramFiles\Cloudbase Solutions\Cloudbase-Init\conf\cloudbase-init.conf"

    Write-Output "Running cloudbase-init SetSetupComplete.cmd"
    $setupCompleteScript = Join-Path $env:windir "Setup\Scripts\SetupComplete.cmd"
    if(Test-Path $setupCompleteScript) {
        Remove-Item -Force $setupCompleteScript
    }
    & "$env:ProgramFiles\Cloudbase Solutions\Cloudbase-Init\bin\SetSetupComplete.cmd"
    if ($LASTEXITCODE) {
        Throw "Failed to run Cloudbase-Init\bin\SetSetupComplete.cmd"
    }
}

function Install-Wins {
    Write-Output "Installing Wins Windows service"
    Start-FileDownload "https://github.com/rancher/wins/releases/download/${WINS_VERSION}/wins.exe" "$KUBERNETES_DIR\wins.exe"
    wins.exe srv app run --register
    if($LASTEXITCODE) {
        Throw "Failed to register wins Windows service"
    }
    Start-Service -Name "rancher-wins"
}

function Start-DockerImagesPull {
    Confirm-EnvVarsAreSet -EnvVars @(
        "ACR_NAME",
        "ACR_USER_NAME",
        "ACR_USER_PASSWORD",
        "KUBERNETES_VERSION")

    docker login "${env:ACR_NAME}.azurecr.io" -u "${env:ACR_USER_NAME}" -p "${env:ACR_USER_PASSWORD}"
    if($LASTEXITCODE) {
        Throw "Failed to login to registry ${env:ACR_NAME}.azurecr.io"
    }
    $images = Get-ContainerImages -ContainerRegistry "${env:ACR_NAME}.azurecr.io" -KubernetesVersion $env:KUBERNETES_VERSION
    foreach($img in $images) {
        Start-ExecuteWithRetry {
            docker.exe image pull $img
            if($LASTEXITCODE) {
                Throw "Failed to pull image: $img"
            }
        }
    }
    docker logout "${env:ACR_NAME}.azurecr.io"
    if($LASTEXITCODE) {
        Throw "Failed to logout from registry ${env:ACR_NAME}.azurecr.io"
    }
}

function Start-ContainerdImagesPull {
    Confirm-EnvVarsAreSet -EnvVars @(
        "ACR_NAME",
        "ACR_USER_NAME",
        "ACR_USER_PASSWORD",
        "KUBERNETES_VERSION")

    $images = Get-ContainerImages -ContainerRegistry "${env:ACR_NAME}.azurecr.io" -KubernetesVersion $env:KUBERNETES_VERSION
    foreach($img in $images) {
        Start-ExecuteWithRetry {
            ctr.exe -n k8s.io image pull -u "${env:ACR_USER_NAME}:${env:ACR_USER_PASSWORD}" $img
            if($LASTEXITCODE) {
                Throw "Failed to pull image: $img"
            }
        }
    }
}

function Install-Containerd {
    Install-NSSM

    $directories = @(
        $CONTAINERD_DIR,
        $VAR_LOG_DIR
    )
    foreach ($dir in $directories) {
        New-Item -ItemType Directory -Force -Path $dir
    }

    Start-FileDownload "https://github.com/containerd/containerd/releases/download/${CRI_CONTAINERD_VERSION}/cri-containerd-cni-$($CRI_CONTAINERD_VERSION.Trim('v'))-windows-amd64.tar.gz" "$env:TEMP\cri-containerd-windows-amd64.tar.gz"
    tar xzf $env:TEMP\cri-containerd-windows-amd64.tar.gz -C $CONTAINERD_DIR
    if($LASTEXITCODE) {
        Throw "Failed to unzip containerd.zip"
    }
    Remove-Item -Force "$env:TEMP\cri-containerd-windows-amd64.tar.gz"

    Start-FileDownload "https://github.com/kubernetes-sigs/cri-tools/releases/download/${CRICTL_VERSION}/crictl-${CRICTL_VERSION}-windows-amd64.tar.gz" "$env:TEMP\crictl-windows-amd64.tar.gz"
    tar xzf $env:TEMP\crictl-windows-amd64.tar.gz -C $CONTAINERD_DIR
    if($LASTEXITCODE) {
        Throw "Failed to unzip crictl.zip"
    }
    Remove-Item -Force "$env:TEMP\crictl-windows-amd64.tar.gz"

    $k8sPauseImage = Get-KubernetesPauseImage
    Get-Content "$PSScriptRoot\containerd\config.toml" | `
        ForEach-Object { $_ -replace "{{K8S_PAUSE_IMAGE}}", $k8sPauseImage } | `
        Out-File "$CONTAINERD_DIR\config.toml" -Encoding ascii

    nssm install containerd $CONTAINERD_DIR\containerd.exe --config $CONTAINERD_DIR\config.toml
    if($LASTEXITCODE) {
        Throw "Failed to install containerd service"
    }
    nssm set containerd AppStdout $VAR_LOG_DIR\containerd.log
    if($LASTEXITCODE) {
        Throw "Failed to set AppStdout for containerd service"
    }
    nssm set containerd AppStderr $VAR_LOG_DIR\containerd.log
    if($LASTEXITCODE) {
        Throw "Failed to set AppStderr for containerd service"
    }
    nssm set containerd Start SERVICE_AUTO_START
    if($LASTEXITCODE) {
        Throw "Failed to set containerd automatic startup type"
    }

    $env:CONTAINER_RUNTIME_ENDPOINT = "npipe:\\.\pipe\containerd-containerd"
    [Environment]::SetEnvironmentVariable("CONTAINER_RUNTIME_ENDPOINT", $env:CONTAINER_RUNTIME_ENDPOINT, [System.EnvironmentVariableTarget]::Machine)

    Add-ToSystemPath $CONTAINERD_DIR
}

function Install-Docker {
    Install-PackageProvider -Name "NuGet" -Force -Confirm:$false
    Install-Module -Repository "PSGallery" -Name "DockerMsftProvider" -Force -Confirm:$false
    Install-Package -ProviderName "DockerMsftProvider" -Name "Docker" -Force -Confirm:$false

    $configDir = Join-Path $env:ProgramData "docker\config"
    New-Item -ItemType Directory -Force -Path $configDir
    Set-Content -Path "${configDir}\daemon.json" -Value '{ "bridge" : "none" }' -Encoding Ascii

    Set-Service -Name "Docker" -StartupType Automatic
}

function Install-ContainerdKubernetesNode {
    Confirm-EnvVarsAreSet -EnvVars @(
        "ACR_NAME",
        "ACR_USER_NAME",
        "ACR_USER_PASSWORD",
        "KUBERNETES_VERSION")

    New-Item -ItemType Directory -Force -Path $TMP_DIR

    Install-Kubelet -KubernetesVersion $env:KUBERNETES_VERSION
    Start-ContainerdImagesPull

    nssm stop containerd
    if($LASTEXITCODE) {
        Throw "Failed to stop containerd"
    }
    Remove-Item -Force "${VAR_LOG_DIR}\containerd.log"

    $hnsNetworks = Get-HnsNetwork
    if($hnsNetworks) {
        $hnsNetworks | Remove-HnsNetwork
    }
}

function Install-DockerKubernetesNode {
    Confirm-EnvVarsAreSet -EnvVars @(
        "ACR_NAME",
        "ACR_USER_NAME",
        "ACR_USER_PASSWORD",
        "KUBERNETES_VERSION")

    New-Item -ItemType Directory -Force -Path $TMP_DIR

    Install-Kubelet -KubernetesVersion $env:KUBERNETES_VERSION
    Start-DockerImagesPull

    Stop-Service "Docker"

    $hnsNetworks = Get-HnsNetwork
    if($hnsNetworks) {
        $hnsNetworks | Remove-HnsNetwork
    }
}
