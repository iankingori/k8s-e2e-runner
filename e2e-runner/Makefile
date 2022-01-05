REGISTRY := docker.io/e2eteam

.PHONY: all
all: docker-build docker-push

.PHONY: docker-push
docker-push:
	docker push $(REGISTRY)/k8s-e2e-runner:latest

.PHONY: docker-build
docker-build:
	docker build -t $(REGISTRY)/k8s-e2e-runner:latest .
