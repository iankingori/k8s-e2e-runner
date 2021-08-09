ARG flannelVersion="v0.14.0"
ARG servercoreTag="ltsc2019"

FROM mcr.microsoft.com/windows/servercore:${servercoreTag}
SHELL ["powershell", "-NoLogo", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

ARG flannelVersion

RUN mkdir -force C:\k\flannel; \
    pushd C:\k\flannel; \
    Write-Output ${env:flannelVersion}; \
    curl.exe -LO https://github.com/coreos/flannel/releases/download/${env:flannelVersion}/flanneld.exe

RUN mkdir C:\utils; \
    curl.exe -Lo C:\utils\wins.exe https://github.com/rancher/wins/releases/download/v0.1.1/wins.exe; \
    curl.exe -Lo C:\utils\yq.exe https://github.com/mikefarah/yq/releases/download/v4.11.2/yq_windows_amd64.exe; \
    "[Environment]::SetEnvironmentVariable('PATH', $env:PATH + ';C:\utils', [EnvironmentVariableTarget]::Machine)"
