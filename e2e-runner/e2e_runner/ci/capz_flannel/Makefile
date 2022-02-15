REGISTRY := k8swin.azurecr.io
FLANNEL_VERSION ?= v0.15.1
KUBERNETES_VERSION ?= v1.23.3

.PHONY: all
all: buildx-flannel buildx-kube-proxy

.PHONY: buildx-flannel
buildx-flannel: buildx-flannel-ltsc2019 buildx-flannel-ltsc2022

.PHONY: buildx-kube-proxy
buildx-kube-proxy: buildx-kube-proxy-ltsc2019 buildx-kube-proxy-ltsc2022

.PHONY: buildx-flannel-ltsc2019
buildx-flannel-ltsc2019:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/powershell:lts-nanoserver-1809 \
		--build-arg FLANNEL_VERSION=$(FLANNEL_VERSION) \
		-t $(REGISTRY)/flannel-windows:$(FLANNEL_VERSION)-nanoserver-ltsc2019 \
		-f ./flannel/kube-flannel-windows.Dockerfile .

.PHONY: buildx-flannel-ltsc2022
buildx-flannel-ltsc2022:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/powershell:lts-nanoserver-ltsc2022 \
		--build-arg FLANNEL_VERSION=$(FLANNEL_VERSION) \
		-t $(REGISTRY)/flannel-windows:$(FLANNEL_VERSION)-nanoserver-ltsc2022 \
		-f ./flannel/kube-flannel-windows.Dockerfile .

.PHONY: buildx-kube-proxy-ltsc2019
buildx-kube-proxy-ltsc2019:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/powershell:lts-nanoserver-1809 \
		--build-arg K8S_VERSION=$(KUBERNETES_VERSION) \
		-t $(REGISTRY)/kube-proxy-windows:$(KUBERNETES_VERSION)-nanoserver-ltsc2019 \
		-f ./kube-proxy/kube-proxy-windows.Dockerfile .

.PHONY: buildx-kube-proxy-ltsc2022
buildx-kube-proxy-ltsc2022:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		--build-arg BASE_IMAGE=mcr.microsoft.com/powershell:lts-nanoserver-ltsc2022 \
		--build-arg K8S_VERSION=$(KUBERNETES_VERSION) \
		-t $(REGISTRY)/kube-proxy-windows:$(KUBERNETES_VERSION)-nanoserver-ltsc2022 \
		-f ./kube-proxy/kube-proxy-windows.Dockerfile .
