REGISTRY ?= ghcr.io/e2e-win

.PHONY: all
all: buildx-flannel-windows buildx-kube-proxy-windows

.PHONY: buildx-flannel-windows
buildx-flannel-windows:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		-t $(REGISTRY)/flannel-windows-hpc:dev \
		./flannel/flannel-windows-hpc

.PHONY: buildx-kube-proxy-windows
buildx-kube-proxy-windows:
	docker buildx build \
		--progress=plain --no-cache --pull --platform windows/amd64 --output=type=registry \
		-t $(REGISTRY)/kube-proxy-windows-hpc:dev \
		./kube-proxy/kube-proxy-windows-hpc
