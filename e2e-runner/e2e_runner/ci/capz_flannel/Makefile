REGISTRY ?= ghcr.io/e2e-win

.PHONY: all
all: buildx-flannel-windows buildx-kube-proxy

.PHONY: buildx-flannel-windows
buildx-flannel-windows:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		-t $(REGISTRY)/flannel-windows-hpc:dev \
		./flannel/flannel-windows-hpc

.PHONY: buildx-kube-proxy
buildx-kube-proxy: \
	buildx-kube-proxy-containerd-ltsc2019 \
	buildx-kube-proxy-containerd-ltsc2022

.PHONY: buildx-kube-proxy-containerd-ltsc2019
buildx-kube-proxy-containerd-ltsc2019:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/windows/nanoserver:1809 \
		-t $(REGISTRY)/kube-proxy-containerd-windows:nanoserver-ltsc2019 \
		./kube-proxy/windows/containerd

.PHONY: buildx-kube-proxy-containerd-ltsc2022
buildx-kube-proxy-containerd-ltsc2022:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/windows/nanoserver:ltsc2022 \
		-t $(REGISTRY)/kube-proxy-containerd-windows:nanoserver-ltsc2022 \
		./kube-proxy/windows/containerd
