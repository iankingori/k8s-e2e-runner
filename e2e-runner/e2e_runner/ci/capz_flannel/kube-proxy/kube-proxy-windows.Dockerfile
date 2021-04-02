ARG k8sVersion="v1.18.6"
ARG servercoreTag="ltsc2019"

FROM mcr.microsoft.com/windows/servercore:${servercoreTag}
SHELL ["powershell", "-NoLogo", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

ARG k8sVersion

RUN mkdir -force C:\k\kube-proxy; \
    pushd C:\k\kube-proxy; \
    Write-Output ${env:k8sVersion}; \
    curl.exe --fail -sLO https://dl.k8s.io/${env:k8sVersion}/bin/windows/amd64/kube-proxy.exe

RUN mkdir C:\utils; \
    curl.exe --fail -sLo C:\utils\wins.exe https://github.com/rancher/wins/releases/download/v0.1.0/wins.exe; \
    curl.exe --fail -sLo C:\utils\yq.exe https://github.com/mikefarah/yq/releases/download/v4.6.3/yq_windows_amd64.exe; \
    "[Environment]::SetEnvironmentVariable('PATH', $env:PATH + ';C:\utils', [EnvironmentVariableTarget]::Machine)"
