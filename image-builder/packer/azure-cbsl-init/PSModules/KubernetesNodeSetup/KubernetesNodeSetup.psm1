$ErrorActionPreference = "Stop"

function Install-LatestWindowsUpdates {
    Param(
        #
        # For each release, the array needs to have items given as:
        # @{
        #   "ID" = "KB4577069"
        #   "URL" = "http://download.windowsupdate.com/c/.../.../KB4577069.msu"
        # }
        #
        # NOTE: Only *.msu packages must be given.
        #
        [Hashtable]$ExtraUpdates=@{
            "ltsc2019" = @()
            "1909" = @()
            "2004" = @()
        }
    )

    Write-Output "Installing PSWindowsUpdate PowerShell module"
    Install-PackageProvider -Name NuGet -Force -Confirm:$false
    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
    Install-Module -Name PSWindowsUpdate -Force -Confirm:$false

    Write-Output "Installing latest Windows updates"
    Start-ExecuteWithRetry `
        -ScriptBlock { Install-WindowsUpdate -AcceptAll -IgnoreReboot } `
        -MaxRetryCount 10 -RetryInterval 30 -RetryMessage "Failed to install Windows updates"

    $release = Get-WindowsRelease
    foreach($update in $ExtraUpdates[$release]) {
        $hotfix = Get-HotFix -Id $update["ID"] -ErrorAction SilentlyContinue
        if($hotfix) {
            Write-Output "HotFix $($update["ID"]) is already installed"
            continue
        }
        $localPath = Join-Path $env:TEMP "$($update["ID"]).msu"
        Start-FileDownload $update["URL"] $localPath
        Write-Output "Installing $localPath"
        $p = Start-Process -Wait -PassThru -FilePath "wusa.exe" `
                        -ArgumentList @($localPath, "/quiet", "/norestart")
        switch($p.ExitCode) {
            0 {
                Write-Output "Succesfully installed $localPath"
            }
            3010 {
                Write-Output "Succesfully installed $localPath. Reboot required"
            }
            Default {
                Throw "Failed to install $localPath"
            }
        }
        $hotfix = Get-HotFix -Id $update["ID"] -ErrorAction SilentlyContinue
        if(!$hotfix) {
            Throw "Couldn't find $($update["ID"]) after finishing the wusa.exe installation"
        }
    }
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

function Disable-Docker {
    # Return early if Docker is not installed
    $dockerdBin = Get-Command "dockerd" -ErrorAction SilentlyContinue
    if(!$dockerdBin) {
        return
    }

    # Disable Docker system service
    Stop-Service -Name "Docker"
    Set-Service -Name "Docker" -StartupType Disabled

    # Remove Docker from the system PATH
    $systemPath = [Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::Machine).Split(';')
    $newSystemPath = $systemPath | Where-Object { $_ -ne "${env:ProgramFiles}\Docker" }
    [Environment]::SetEnvironmentVariable("PATH", ($newSystemPath -join ';'), [System.EnvironmentVariableTarget]::Machine)
}

function Install-Containerd {
    mkdir -force $CONTAINERD_DIR
    mkdir -force $KUBERNETES_DIR
    mkdir -force $VAR_LOG_DIR
    mkdir -force "$ETC_DIR\cni\net.d"
    mkdir -force "$OPT_DIR\cni\bin"

    Start-FileDownload "https://github.com/containerd/containerd/releases/download/v${CRI_CONTAINERD_VERSION}/cri-containerd-cni-${CRI_CONTAINERD_VERSION}-windows-amd64.tar.gz" "$env:TEMP\cri-containerd-windows-amd64.tar.gz"
    tar xzf $env:TEMP\cri-containerd-windows-amd64.tar.gz -C $CONTAINERD_DIR
    if($LASTEXITCODE) {
        Throw "Failed to unzip containerd.zip"
    }
    Add-ToSystemPath $CONTAINERD_DIR
    Remove-Item -Force "$env:TEMP\cri-containerd-windows-amd64.tar.gz"

    Start-FileDownload "https://github.com/kubernetes-sigs/cri-tools/releases/download/v${CRICTL_VERSION}/crictl-v${CRICTL_VERSION}-windows-amd64.tar.gz" "$env:TEMP\crictl-windows-amd64.tar.gz"
    tar xzf $env:TEMP\crictl-windows-amd64.tar.gz -C $KUBERNETES_DIR
    if($LASTEXITCODE) {
        Throw "Failed to unzip crictl.zip"
    }
    Remove-Item -Force "$env:TEMP\crictl-windows-amd64.tar.gz"

    Copy-Item "$PSScriptRoot\containerd\nat.conf" "$ETC_DIR\cni\net.d\"
    foreach($cniBin in @("nat.exe", "sdnbridge.exe", "sdnoverlay.exe")) {
        Move-Item "$CONTAINERD_DIR\cni\$cniBin" "$OPT_DIR\cni\bin\"
    }
    $k8sPauseImage = Get-KubernetesPauseImage
    Get-Content "$PSScriptRoot\containerd\config.toml" | `
        ForEach-Object { $_ -replace "{{K8S_PAUSE_IMAGE}}", $k8sPauseImage } | `
        Out-File "$CONTAINERD_DIR\config.toml" -Encoding ascii

    # TODO: Remove these binaries downloads, once those bundled with the stable package pass Windows conformance testing.
    Start-FileDownload "https://capzwin.blob.core.windows.net/bin/containerd-shim-runhcs-v1.exe" "$CONTAINERD_DIR\containerd-shim-runhcs-v1.exe"
    foreach($cniBin in @("nat.exe", "sdnbridge.exe", "sdnoverlay.exe")) {
        Start-FileDownload "https://capzwin.blob.core.windows.net/bin/$cniBin" "$OPT_DIR\cni\bin\$cniBin"
    }

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

    nssm set containerd Start SERVICE_DEMAND_START
    if($LASTEXITCODE) {
        Throw "Failed to set containerd manual start type"
    }

    $env:CONTAINER_RUNTIME_ENDPOINT = "npipe:\\.\pipe\containerd-containerd"
    [Environment]::SetEnvironmentVariable("CONTAINER_RUNTIME_ENDPOINT", $env:CONTAINER_RUNTIME_ENDPOINT, [System.EnvironmentVariableTarget]::Machine)

    Start-Service -Name "containerd"
}

function Set-DockerConfig {
    Set-Content -Path "$env:ProgramData\docker\config\daemon.json" `
                -Value '{ "bridge" : "none" }' -Encoding Ascii

    Set-Service -Name "docker" -StartupType Manual
}

function Install-ContainerdKubernetesNode {
    Param(
        [String]$KubernetesVersion="v1.22.0"
    )

    Confirm-EnvVarsAreSet -EnvVars @("ACR_NAME", "ACR_USER_NAME", "ACR_USER_PASSWORD")
    Disable-Docker
    Install-NSSM
    Install-Containerd
    Install-Kubelet -KubernetesVersion $KubernetesVersion -ContainerRuntimeServiceName "containerd"
    Install-ContainerNetworkingPlugins

    $images = Get-ContainerImages -ContainerRegistry "${env:ACR_NAME}.azurecr.io" -KubernetesVersion $KubernetesVersion
    foreach($img in $images) {
        Start-ExecuteWithRetry {
            ctr.exe -n k8s.io image pull -u "${env:ACR_USER_NAME}:${env:ACR_USER_PASSWORD}" $img
            if($LASTEXITCODE) {
                Throw "Failed to pull image: $img"
            }
        }
    }

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
    Param(
        [String]$KubernetesVersion="v1.22.0"
    )

    Confirm-EnvVarsAreSet -EnvVars @("ACR_NAME", "ACR_USER_NAME", "ACR_USER_PASSWORD")
    Install-NSSM
    Set-DockerConfig
    Install-Kubelet -KubernetesVersion $KubernetesVersion -ContainerRuntimeServiceName "docker"
    Install-ContainerNetworkingPlugins

    docker login "${env:ACR_NAME}.azurecr.io" -u "${env:ACR_USER_NAME}" -p "${env:ACR_USER_PASSWORD}"
    if($LASTEXITCODE) {
        Throw "Failed to login to login to registry ${env:ACR_NAME}.azurecr.io"
    }
    $images = Get-ContainerImages -ContainerRegistry "${env:ACR_NAME}.azurecr.io" -KubernetesVersion $KubernetesVersion
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
        Throw "Failed to login from registry ${env:ACR_NAME}.azurecr.io"
    }
    Stop-Service "Docker"

    $hnsNetworks = Get-HnsNetwork
    if($hnsNetworks) {
        $hnsNetworks | Remove-HnsNetwork
    }
}
