ARG BASE_IMAGE="mcr.microsoft.com/powershell:lts-nanoserver-1809"
ARG WINS_VERSION="v0.1.1"
ARG YQ_VERSION="v4.20.2"
ARG K8S_VERSION="v1.24.2"

# Linux stage
FROM --platform=linux/amd64 alpine:latest as prep

ARG WINS_VERSION
ARG YQ_VERSION
ARG K8S_VERSION

RUN mkdir -p /k/kube-proxy

ADD https://github.com/rancher/wins/releases/download/${WINS_VERSION}/wins.exe /wins.exe
ADD https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_windows_amd64.exe /yq.exe
ADD https://dl.k8s.io/${K8S_VERSION}/bin/windows/amd64/kube-proxy.exe /k/kube-proxy/kube-proxy.exe

# Golang build stage
FROM --platform=linux/amd64 golang:latest as gobuilder

ADD exec_ps.go /tmp/exec_ps.go
RUN GOOS=windows GOARCH=amd64 go build -o /tmp/exec_ps.exe /tmp/exec_ps.go

# Windows stage
FROM $BASE_IMAGE

COPY --from=prep /k /k
COPY --from=prep /wins.exe /Windows/System32/wins.exe
COPY --from=prep /yq.exe /Windows/System32/yq.exe
COPY --from=gobuilder /tmp/exec_ps.exe /k/kube-proxy/exec_ps.exe

USER ContainerAdministrator

ENV PATH="C:\Windows\system32;C:\Windows;C:\Program Files\PowerShell"
