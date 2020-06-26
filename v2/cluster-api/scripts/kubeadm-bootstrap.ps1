Param(
    [parameter(Mandatory=$true)]
    [string]$CIVersion,
    [parameter(Mandatory=$true)]
    [string]$CIPackagesBaseURL
)

$ErrorActionPreference = "Stop"

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
        Write-Output "Start-ExecuteWithRetry attempt $retryCount"
        try {
            $res = Invoke-Command -ScriptBlock $ScriptBlock `
                                  -ArgumentList $ArgumentList
            $ErrorActionPreference = $currentErrorActionPreference
            Write-Output "Start-ExecuteWithRetry terminated"
            return $res
        } catch [System.Exception] {
            $retryCount++
            if ($retryCount -gt $MaxRetryCount) {
                $ErrorActionPreference = $currentErrorActionPreference
                Write-Output "Start-ExecuteWithRetry exception thrown"
                throw
            } else {
                if($RetryMessage) {
                    Write-Output "Start-ExecuteWithRetry RetryMessage: $RetryMessage"
                } elseif($_) {
                    Write-Output "Start-ExecuteWithRetry Retry: $_.ToString()"
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
    Start-ExecuteWithRetry -ScriptBlock {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($URL, $Destination)
    } -MaxRetryCount $RetryCount -RetryInterval 3 -RetryMessage "Failed to download $URL. Retrying"
}

$global:KubernetesPath = "$env:SystemDrive\k"

iex "nssm stop kubelet"
Stop-Service -Force -Name Docker

Start-FileDownload "$CIPackagesBaseURL/$CIVersion/bin/windows/amd64/kubelet.exe" "$global:KubernetesPath\kubelet.exe"
Start-FileDownload "$CIPackagesBaseURL/$CIVersion/bin/windows/amd64/kubeadm.exe" "$global:KubernetesPath\kubeadm.exe"

Get-HnsNetwork | Remove-HnsNetwork
Get-NetAdapter -Physical | Rename-NetAdapter -NewName "Ethernet"

Start-Service -Name Docker
iex "nssm start kubelet"

Start-FileDownload "$CIPackagesBaseURL/$CIVersion/images/kube-proxy-windows.tar" "/tmp/kube-proxy-windows.tar"
iex "docker.exe image load -i /tmp/kube-proxy-windows.tar"
rm /tmp/kube-proxy-windows.tar
