ARG BASE_IMAGE="mcr.microsoft.com/windows/nanoserver:1809"
ARG FLANNEL_VERSION="v0.19.2"
ARG CNI_PLUGINS_VERSION="v1.1.1"
ARG WINDOWS_CNI_PLUGINS_VERSION="v0.3.0"
ARG FLANNEL_CNI_PLUGIN_VERSION="v1.1.0"

# Linux stage
FROM --platform=linux/amd64 alpine:latest as prep

ARG FLANNEL_VERSION
ARG CNI_PLUGINS_VERSION
ARG WINDOWS_CNI_PLUGINS_VERSION
ARG FLANNEL_CNI_PLUGIN_VERSION

RUN mkdir -p /flannel /cni/bin
ADD https://github.com/coreos/flannel/releases/download/${FLANNEL_VERSION}/flanneld.exe /flannel/flanneld.exe
ADD https://github.com/containernetworking/plugins/releases/download/${CNI_PLUGINS_VERSION}/cni-plugins-windows-amd64-${CNI_PLUGINS_VERSION}.tgz /cni-plugins.tgz
ADD https://github.com/microsoft/windows-container-networking/releases/download/${WINDOWS_CNI_PLUGINS_VERSION}/windows-container-networking-cni-amd64-${WINDOWS_CNI_PLUGINS_VERSION}.zip /windows-cni-plugins.zip
ADD https://github.com/flannel-io/cni-plugin/releases/download/${FLANNEL_CNI_PLUGIN_VERSION}/flannel-amd64.exe /cni/bin/flannel.exe
RUN tar -xzvf /cni-plugins.tgz -C /cni/bin
RUN unzip /windows-cni-plugins.zip -d /cni/bin

# Golang build stage
FROM --platform=linux/amd64 golang:latest as gobuilder

ADD flannel-windows /flannel-windows
WORKDIR /flannel-windows
ENV GOOS=windows GOARCH=amd64
RUN go build -ldflags="-s -w" -o install-cni.exe ./cmd/install-cni
RUN go build -ldflags="-s -w" -o run.exe ./cmd/run

# Windows stage
FROM $BASE_IMAGE

COPY --from=prep /flannel /flannel
COPY --from=prep /cni /cni
COPY --from=gobuilder /flannel-windows/install-cni.exe /flannel/install-cni.exe
COPY --from=gobuilder /flannel-windows/run.exe /flannel/run.exe

ENV PATH="C:\Windows\system32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0"

ENTRYPOINT ["%CONTAINER_SANDBOX_MOUNT_POINT%\\flannel\\run.exe"]
