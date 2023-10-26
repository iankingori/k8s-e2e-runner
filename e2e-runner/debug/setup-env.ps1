$ErrorActionPreference = "Stop"

$HELPER_DOCKER_IMAGE = "alpine:3.18"

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

Confirm-EnvVarsAreSet -EnvVars @(
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET")

mkdir -p $PSScriptRoot/.env/ssh
ssh-keygen.exe -N "" -C "" -f $PSScriptRoot/.env/ssh/id_rsa
if($LASTEXITCODE) {
    Throw "Failed to generate SSH keypairs"
}
docker.exe run --rm -v $PSScriptRoot/.env:/env $HELPER_DOCKER_IMAGE chmod 600 /env/ssh/id_rsa
if($LASTEXITCODE) {
    Throw "Failed to run chmod in docker container mount"
}

mkdir -p $PSScriptRoot/.env/docker-creds
if ($env:DOCKER_CONFIG_FILE) {
    cp $env:DOCKER_CONFIG_FILE $PSScriptRoot/.env/docker-creds/config.json
    docker.exe run --rm -v $PSScriptRoot/.env:/env $HELPER_DOCKER_IMAGE chmod 600 /env/docker-creds/config.json
    if($LASTEXITCODE) {
        Throw "Failed to run chmod in docker container mount"
    }
}

$envFile = "$PSScriptRoot/.env/env.sh"
if (Test-Path $envFile) {
    rm -force $envFile
}

echo "AZURE_SUBSCRIPTION_ID=$env:AZURE_SUBSCRIPTION_ID" | Out-File -Encoding ascii -Append $envFile
echo "AZURE_TENANT_ID=$env:AZURE_TENANT_ID" | Out-File -Encoding ascii -Append $envFile
echo "AZURE_CLIENT_ID=$env:AZURE_CLIENT_ID" | Out-File -Encoding ascii -Append $envFile
echo "AZURE_CLIENT_SECRET=$env:AZURE_CLIENT_SECRET" | Out-File -Encoding ascii -Append $envFile

echo "SSH_PRIVATE_KEY_PATH=/root/.ssh/id_rsa" | Out-File -Encoding ascii -Append $envFile
echo "SSH_PUBLIC_KEY_PATH=/root/.ssh/id_rsa.pub" | Out-File -Encoding ascii -Append $envFile
