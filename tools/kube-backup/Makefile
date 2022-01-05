REGISTRY := docker.io/e2eteam

.PHONY: all
all: docker-build docker-push

.PHONY: docker-push
docker-push:
	docker push $(REGISTRY)/kube-backup:latest

.PHONY: docker-build
docker-build:
	docker build -t $(REGISTRY)/kube-backup:latest .
