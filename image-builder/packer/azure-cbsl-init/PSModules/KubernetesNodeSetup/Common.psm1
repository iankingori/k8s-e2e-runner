$ErrorActionPreference = "Stop"

$global:KUBERNETES_DIR = Join-Path $env:SystemDrive "k"
$global:VAR_LOG_DIR = Join-Path $env:SystemDrive "var\log"
$global:VAR_LIB_DIR = Join-Path $env:SystemDrive "var\lib"
$global:ETC_DIR = Join-Path $env:SystemDrive "etc"
$global:NSSM_DIR = Join-Path $env:ProgramFiles "nssm"

# https://github.com/flannel-io/flannel/releases
$global:FLANNEL_VERSION = "v0.15.0"

$global:NSSM_URL = "https://k8stestinfrabinaries.blob.core.windows.net/nssm-mirror/nssm-2.24.zip"


function Start-ExecuteWithRetry {
    Param(
        [Parameter(Mandatory=$true)]
        [ScriptBlock]$ScriptBlock,
        [int]$MaxRetryCount=10,
        [int]$RetryInterval=3,
        [string]$RetryMessage,
        [array]$ArgumentList=@()
    )
    $currentErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $retryCount = 0
    while ($true) {
        try {
            $res = Invoke-Command -ScriptBlock $ScriptBlock `
                                  -ArgumentList $ArgumentList
            $ErrorActionPreference = $currentErrorActionPreference
            return $res
        } catch [System.Exception] {
            $retryCount++
            if ($retryCount -gt $MaxRetryCount) {
                $ErrorActionPreference = $currentErrorActionPreference
                throw
            } else {
                if($RetryMessage) {
                    Write-Output "Retry (${retryCount}/${MaxRetryCount}): $RetryMessage"
                } elseif($_) {
                    Write-Output "Retry (${retryCount}/${MaxRetryCount}): $_"
                }
                Start-Sleep $RetryInterval
            }
        }
    }
}

function Start-FileDownload {
    Param(
        [Parameter(Mandatory=$true)]
        [string]$URL,
        [Parameter(Mandatory=$true)]
        [string]$Destination,
        [Parameter(Mandatory=$false)]
        [int]$RetryCount=10
    )
    Write-Output "Downloading $URL to $Destination"
    Start-ExecuteWithRetry -ScriptBlock {
        Invoke-Expression "curl.exe -L -s -o $Destination $URL"
    } -MaxRetryCount $RetryCount -RetryInterval 3 -RetryMessage "Failed to download $URL. Retrying"
}

function Add-ToSystemPath {
    Param(
        [Parameter(Mandatory=$false)]
        [string[]]$Path
    )

    if(!$Path) {
        return
    }

    $systemPath = [Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::Machine).Split(';')
    $currentPath = $env:PATH.Split(';')
    foreach($p in $Path) {
        if($p -notin $systemPath) {
            $systemPath += $p
        }
        if($p -notin $currentPath) {
            $currentPath += $p
        }
    }

    $env:PATH = $currentPath -join ';'
    $newSystemPath = $systemPath -join ';'
    [Environment]::SetEnvironmentVariable("PATH", $newSystemPath, [System.EnvironmentVariableTarget]::Machine)
}

function Get-WindowsRelease {
    $releases = @{
        17763 = "ltsc2019"
        19041 = "2004"
        20348 = "ltsc2022"
    }
    $osBuild = [System.Environment]::OSVersion.Version.Build
    $releaseName = $releases[$osBuild]
    if (!$releaseName) {
        Throw "Cannot find the Windows release name"
    }
    return $releaseName
}

function Get-NanoServerImage {
    $release = Get-WindowsRelease
    if($release -eq "ltsc2019") {
        $release = "1809"
    }
    return "mcr.microsoft.com/windows/nanoserver:$release"
}

function Get-ServerCoreImage {
    $release = Get-WindowsRelease
    return "mcr.microsoft.com/windows/servercore:$release"
}

function Get-KubernetesPauseImage {
    return "mcr.microsoft.com/oss/kubernetes/pause:3.6"
}

function Get-ContainerRuntime {
    $dockerdBin = Get-Command "dockerd" -ErrorAction SilentlyContinue
    if($dockerdBin) {
        return "docker"
    }
    $containerd = Get-Command "containerd" -ErrorAction SilentlyContinue
    if($containerd) {
        return "containerd"
    }
    Throw "Could not find any container runtime installed"
}

function Install-NSSM {
    Write-Output "Installing NSSM"
    $nssm = Get-Command "nssm" -ErrorAction SilentlyContinue
    if($nssm) {
        Write-Output "NSSM is already installed"
        return
    }

    New-Item -ItemType Directory -Force -Path $NSSM_DIR

    Start-FileDownload $NSSM_URL "$env:TEMP\nssm.zip"
    tar -C "$NSSM_DIR" -xvf $env:TEMP\nssm.zip --strip-components 2 */win64/*.exe
    if($LASTEXITCODE) {
        Throw "Failed to unzip nssm.zip"
    }

    Remove-Item -Force "$env:TEMP\nssm.zip"
    Add-ToSystemPath $NSSM_DIR
}

function Install-Kubelet {
    Param(
        [Parameter(Mandatory=$true)]
        [string]$KubernetesVersion
    )

    Install-NSSM

    $directories = @(
        $KUBERNETES_DIR,
        "$ETC_DIR\kubernetes\pki",
        "$VAR_LIB_DIR\kubelet\etc\kubernetes",
        "$VAR_LIB_DIR\kubelet\etc\kubernetes\manifests",
        "$VAR_LOG_DIR\kubelet"
    )
    foreach ($dir in $directories) {
        New-Item -ItemType Directory -Force -Path $dir
    }

    Start-FileDownload "https://dl.k8s.io/$KubernetesVersion/bin/windows/amd64/kubelet.exe" "$KUBERNETES_DIR\kubelet.exe"
    Start-FileDownload "https://dl.k8s.io/$KubernetesVersion/bin/windows/amd64/kubeadm.exe" "$KUBERNETES_DIR\kubeadm.exe"

    New-Item -Type SymbolicLink -Force -Path "$VAR_LIB_DIR\kubelet\etc\kubernetes\pki" -Value "$ETC_DIR\kubernetes\pki"
    Copy-Item -Force -Path "$PSScriptRoot\scripts\start-kubelet.ps1" -Destination "$KUBERNETES_DIR\start-kubelet.ps1"

    Write-Output "Registering kubelet service"
    nssm install kubelet (Get-Command powershell).Source "-ExecutionPolicy Bypass -NoProfile -File $KUBERNETES_DIR\start-kubelet.ps1"
    if($LASTEXITCODE) {
        Throw "Failed to register kubelet Windows service"
    }
    nssm set kubelet DependOnService (Get-ContainerRuntime)
    if($LASTEXITCODE) {
        Throw "Failed to set kubelet DependOnService"
    }
    $k8sPauseImage = Get-KubernetesPauseImage
    nssm set kubelet AppEnvironmentExtra K8S_PAUSE_IMAGE=$k8sPauseImage
    if($LASTEXITCODE) {
        Throw "Failed to set kubelet K8S_PAUSE_IMAGE nssm extra env variable"
    }
    nssm set kubelet Start SERVICE_DEMAND_START
    if($LASTEXITCODE) {
        Throw "Failed to set kubelet manual start type"
    }

    Add-ToSystemPath $KUBERNETES_DIR

    New-NetFirewallRule -Name "kubelet" -DisplayName "kubelet" -Enabled True `
                        -Direction Inbound -Protocol TCP -Action Allow -LocalPort 10250
}

function Get-ContainerImages {
    Param(
        [Parameter(Mandatory=$true)]
        [string]$ContainerRegistry,
        [Parameter(Mandatory=$true)]
        [string]$KubernetesVersion
    )

    $windowsRelease = Get-WindowsRelease
    return @(
        (Get-KubernetesPauseImage),
        (Get-NanoServerImage),
        (Get-ServerCoreImage),
        "${ContainerRegistry}/flannel-windows:${FLANNEL_VERSION}-windowsservercore-${windowsRelease}",
        "${ContainerRegistry}/kube-proxy-windows:${KubernetesVersion}-windowsservercore-${windowsRelease}"
    )
}

function Confirm-EnvVarsAreSet {
    Param(
        [String[]]$EnvVars
    )
    foreach($var in $EnvVars) {
        if(!(Test-Path "env:${var}")) {
            Throw "Missing required environment variable: $var"
        }
    }
}

function Install-OpenSSHServer {
    # Install OpenSSH
    Start-ExecuteWithRetry { Get-WindowsCapability -Online -Name OpenSSH* | Add-WindowsCapability -Online }
    Set-Service -Name sshd -StartupType Automatic
    Start-Service sshd

    # Set PowerShell as default shell
    New-ItemProperty `
        -PropertyType String -Force -Name DefaultShell `
        -Path "HKLM:\SOFTWARE\OpenSSH" -Value (Get-Command powershell).Source

    # Remove unified authorized_keys file for admin users
    $configFile = Join-Path $env:ProgramData "ssh\sshd_config"
    $config = Get-Content $configFile | `
        ForEach-Object { $_ -replace '(.*Match Group administrators.*)', '# $1' } | `
        ForEach-Object { $_ -replace '(.*AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys.*)', '# $1' }
    Set-Content -Path $configFile -Value $config -Encoding Ascii
}

function Get-WindowsBuildInfo {
    $p = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    $table = New-Object System.Data.DataTable
    $table.Columns.AddRange(@("Release", "Version", "Build"))
    $table.Rows.Add($p.ProductName, $p.ReleaseId, "$($p.CurrentBuild).$($p.UBR)") | Out-Null
    return $table
}
