ARG BASE_IMAGE="mcr.microsoft.com/windows/servercore:ltsc2019"
ARG WINS_VERSION="v0.1.1"
ARG YQ_VERSION="v4.11.2"
ARG FLANNEL_VERSION="v0.14.0"

# Linux stage
FROM --platform=linux/amd64 alpine:latest as prep

ARG WINS_VERSION
ARG YQ_VERSION
ARG FLANNEL_VERSION

RUN mkdir -p /k/flannel

ADD https://github.com/rancher/wins/releases/download/${WINS_VERSION}/wins.exe /wins.exe
ADD https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_windows_amd64.exe /yq.exe
ADD https://github.com/coreos/flannel/releases/download/${FLANNEL_VERSION}/flanneld.exe /k/flannel/flanneld.exe

# Windows stage
FROM $BASE_IMAGE

COPY --from=prep /k /k
COPY --from=prep /wins.exe /Windows/System32/wins.exe
COPY --from=prep /yq.exe /Windows/System32/yq.exe

ENV PATH="C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0"
