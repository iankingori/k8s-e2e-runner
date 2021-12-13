ARG BASE_IMAGE="mcr.microsoft.com/windows/servercore:ltsc2019"
ARG WINS_VERSION="v0.1.1"
ARG YQ_VERSION="v4.16.1"
ARG K8S_VERSION="v1.23.0"

# Linux stage
FROM --platform=linux/amd64 alpine:latest as prep

ARG WINS_VERSION
ARG YQ_VERSION
ARG K8S_VERSION

RUN mkdir -p /k/kube-proxy

ADD https://github.com/rancher/wins/releases/download/${WINS_VERSION}/wins.exe /wins.exe
ADD https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_windows_amd64.exe /yq.exe
ADD https://dl.k8s.io/${K8S_VERSION}/bin/windows/amd64/kube-proxy.exe /k/kube-proxy/kube-proxy.exe

# Windows stage
FROM $BASE_IMAGE

COPY --from=prep /k /k
COPY --from=prep /wins.exe /Windows/System32/wins.exe
COPY --from=prep /yq.exe /Windows/System32/yq.exe

ENV PATH="C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0"
