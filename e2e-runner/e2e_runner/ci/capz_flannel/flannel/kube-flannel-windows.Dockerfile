ARG BASE_IMAGE="mcr.microsoft.com/powershell:lts-nanoserver-1809"
ARG WINS_VERSION="v0.1.1"
ARG YQ_VERSION="v4.16.1"
ARG FLANNEL_VERSION="v0.15.1"
ARG CNI_PLUGINS_VERSION="v1.0.1"
ARG FLANNEL_CNI_PLUGIN_VERSION="v1.0"

# Linux stage
FROM --platform=linux/amd64 alpine:latest as prep

ARG WINS_VERSION
ARG YQ_VERSION
ARG FLANNEL_VERSION
ARG CNI_PLUGINS_VERSION
ARG FLANNEL_CNI_PLUGIN_VERSION

RUN mkdir -p /k/flannel /opt/cni/bin

ADD https://github.com/rancher/wins/releases/download/${WINS_VERSION}/wins.exe /wins.exe
ADD https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_windows_amd64.exe /yq.exe
ADD https://github.com/coreos/flannel/releases/download/${FLANNEL_VERSION}/flanneld.exe /k/flannel/flanneld.exe
ADD https://github.com/containernetworking/plugins/releases/download/${CNI_PLUGINS_VERSION}/cni-plugins-windows-amd64-${CNI_PLUGINS_VERSION}.tgz /tmp/cni-plugins.tgz
ADD https://github.com/flannel-io/cni-plugin/releases/download/${FLANNEL_CNI_PLUGIN_VERSION}/flannel.exe /opt/cni/bin/flannel.exe

RUN tar -xzvf /tmp/cni-plugins.tgz -C /opt/cni/bin && rm /tmp/cni-plugins.tgz

# Windows stage
FROM $BASE_IMAGE

COPY --from=prep /k /k
COPY --from=prep /opt /opt
COPY --from=prep /wins.exe /Windows/System32/wins.exe
COPY --from=prep /yq.exe /Windows/System32/yq.exe

USER ContainerAdministrator

ENV PATH="C:\Windows\system32;C:\Windows;C:\Program Files\PowerShell"
