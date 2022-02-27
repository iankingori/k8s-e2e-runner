ARG BASE_IMAGE="mcr.microsoft.com/powershell:lts-nanoserver-1809"
ARG K8S_VERSION="v1.23.4"

# Linux stage
FROM --platform=linux/amd64 alpine:latest as prep

ARG K8S_VERSION

RUN mkdir -p /kube-proxy
ADD https://dl.k8s.io/${K8S_VERSION}/bin/windows/amd64/kube-proxy.exe /kube-proxy/kube-proxy.exe

# Golang build stage
FROM --platform=linux/amd64 golang:latest as gobuilder

ADD kube-proxy-windows /kube-proxy-windows
WORKDIR /kube-proxy-windows
ENV GOOS=windows GOARCH=amd64
RUN go build -ldflags="-s -w" -o init.exe ./cmd/init
RUN go build -ldflags="-s -w" -o run.exe ./cmd/run

# Windows stage
FROM $BASE_IMAGE

COPY --from=prep /kube-proxy /kube-proxy
COPY --from=gobuilder /kube-proxy-windows/init.exe /kube-proxy/init.exe
COPY --from=gobuilder /kube-proxy-windows/run.exe /kube-proxy/run.exe

ENV PATH="C:\Windows\system32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0"

ENTRYPOINT ["%CONTAINER_SANDBOX_MOUNT_POINT%\\kube-proxy\\run.exe"]
