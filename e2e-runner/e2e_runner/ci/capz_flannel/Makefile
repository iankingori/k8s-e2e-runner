REGISTRY := k8swin.azurecr.io
FLANNEL_VERSION ?= v0.17.0
KUBERNETES_VERSION ?= v1.23.6

.PHONY: all
all: buildx-flannel buildx-kube-proxy

.PHONY: buildx-flannel
buildx-flannel: \
	buildx-flannel-docker-ltsc2019 \
	buildx-flannel-containerd-ltsc2019 \
	buildx-flannel-containerd-ltsc2022

.PHONY: buildx-kube-proxy
buildx-kube-proxy: \
	buildx-kube-proxy-docker-ltsc2019 \
	buildx-kube-proxy-containerd-ltsc2019 \
	buildx-kube-proxy-containerd-ltsc2022

.PHONY: buildx-flannel-docker-ltsc2019
buildx-flannel-docker-ltsc2019:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/powershell:lts-nanoserver-1809 \
		--build-arg FLANNEL_VERSION=$(FLANNEL_VERSION) \
		-t $(REGISTRY)/flannel-docker-windows:$(FLANNEL_VERSION)-nanoserver-ltsc2019 \
		-f ./flannel/windows/docker/Dockerfile ./flannel/windows/docker

.PHONY: buildx-flannel-containerd-ltsc2019
buildx-flannel-containerd-ltsc2019:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/windows/nanoserver:1809 \
		--build-arg FLANNEL_VERSION=$(FLANNEL_VERSION) \
		-t $(REGISTRY)/flannel-containerd-windows:$(FLANNEL_VERSION)-nanoserver-ltsc2019 \
		-f ./flannel/windows/containerd/Dockerfile ./flannel/windows/containerd

.PHONY: buildx-flannel-containerd-ltsc2022
buildx-flannel-containerd-ltsc2022:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/windows/nanoserver:ltsc2022 \
		--build-arg FLANNEL_VERSION=$(FLANNEL_VERSION) \
		-t $(REGISTRY)/flannel-containerd-windows:$(FLANNEL_VERSION)-nanoserver-ltsc2022 \
		-f ./flannel/windows/containerd/Dockerfile ./flannel/windows/containerd

.PHONY: buildx-kube-proxy-docker-ltsc2019
buildx-kube-proxy-docker-ltsc2019:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/powershell:lts-nanoserver-1809 \
		--build-arg K8S_VERSION=$(KUBERNETES_VERSION) \
		-t $(REGISTRY)/kube-proxy-docker-windows:$(KUBERNETES_VERSION)-nanoserver-ltsc2019 \
		-f ./kube-proxy/windows/docker/Dockerfile .

.PHONY: buildx-kube-proxy-containerd-ltsc2019
buildx-kube-proxy-containerd-ltsc2019:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/windows/nanoserver:1809 \
		--build-arg K8S_VERSION=$(KUBERNETES_VERSION) \
		-t $(REGISTRY)/kube-proxy-containerd-windows:$(KUBERNETES_VERSION)-nanoserver-ltsc2019 \
		-f ./kube-proxy/windows/containerd/Dockerfile ./kube-proxy/windows/containerd

.PHONY: buildx-kube-proxy-containerd-ltsc2022
buildx-kube-proxy-containerd-ltsc2022:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/windows/nanoserver:ltsc2022 \
		--build-arg K8S_VERSION=$(KUBERNETES_VERSION) \
		-t $(REGISTRY)/kube-proxy-containerd-windows:$(KUBERNETES_VERSION)-nanoserver-ltsc2022 \
		-f ./kube-proxy/windows/containerd/Dockerfile ./kube-proxy/windows/containerd
