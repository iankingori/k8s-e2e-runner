$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$logsDir = "/logs"
mkdir -force $logsDir

/k/debug/collectlogs.ps1
if ($LASTEXITCODE) {
    Throw "Failed to execute /k/debug/collectlogs.ps1. Exit code: $LASTEXITCODE"
}

$count = 1
foreach ($i in (Get-ChildItem /k/debug -Directory)) {
    cp -recurse $i.FullName "$logsDir/os-logs-${count}"
    $count++
}
foreach ($i in (Get-ChildItem /k/*.log -File)) {
    cp $i.FullName $logsDir
}

Compress-Archive -Path $logsDir -DestinationPath "${logsDir}.zip"
