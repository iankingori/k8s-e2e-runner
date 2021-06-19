$ErrorActionPreference = "Stop"

$LOGS_DIR = Join-Path $env:SystemDrive "tmp/logs"


function Get-WindowsLogs {
    Write-Output "Collecting Windows logs"

    $logsPath = Join-Path -Path $LOGS_DIR -ChildPath "windows"
    New-Item -ItemType Directory -Path $logsPath -Force | Out-Null

    Get-WinEvent -FilterHashtable @{LogName='System'; id=1074,1076,2004,6005,6006,6008} -ErrorAction SilentlyContinue | `
        Select-Object -Property TimeCreated, Id, LevelDisplayName, Message | Format-List * | `
        Out-File -FilePath "$logsPath\reboots.log" -Encoding Ascii

    Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Windows Error Reporting'} -ErrorAction SilentlyContinue | `
        Select-Object -Property TimeCreated, Id, LevelDisplayName, Message | Format-List * | `
        Out-File -FilePath "$logsPath\crashes.log" -Encoding Ascii
}

function Get-DockerLogs {
    Write-Output "Collecting Docker logs"

    $logsPath = Join-Path -Path $LOGS_DIR -ChildPath "docker"
    New-Item -ItemType Directory -Path $logsPath -Force | Out-Null

    Get-EventLog -LogName Application -Source Docker -ErrorAction SilentlyContinue | `
        Select-Object -Property TimeGenerated, Index, EntryType, Message | Format-List * | `
        Out-File -FilePath "$logsPath\docker.log" -Encoding Ascii
}

function Get-KubernetesLogs {
    Write-Output "Collecting Kubernetes logs"

    $logsPath = Join-Path -Path $LOGS_DIR -ChildPath "kubernetes"
    Copy-Item -Recurse -Force -Path "$env:SystemDrive\var\log" -Destination $logsPath
}

function Get-CloudbaseInitLogs {
    Write-Output "Collecting Cloudbase-Init logs"

    Copy-Item -Recurse -Force `
        -Path "${env:ProgramFiles}\Cloudbase Solutions\Cloudbase-Init\log" `
        -Destination "${LOGS_DIR}\cloudbase-init"
}

if(Test-Path $LOGS_DIR) {
    Remove-Item -Recurse -Force -Path $LOGS_DIR
}
New-Item -ItemType Directory -Path $LOGS_DIR | Out-Null

Get-WindowsLogs
Get-DockerLogs
Get-KubernetesLogs
Get-CloudbaseInitLogs

$archivePath = Join-Path (Split-Path -Path $LOGS_DIR -Parent) "logs.zip"
Compress-Archive -Path $LOGS_DIR -CompressionLevel Optimal -DestinationPath $archivePath -Force
