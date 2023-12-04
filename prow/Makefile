REGISTRY ?= ghcr.io/e2e-win

.PHONY: all
all: update-prow-config update-prow-plugins update-prow-job-config

.PHONY: update-prow-config
update-prow-config:
	kubectl create configmap -n prow config --from-file=config.yaml=config.yaml -o yaml --dry-run=client | kubectl replace configmap -f -

.PHONY: update-prow-plugins
update-prow-plugins:
	kubectl create configmap -n prow plugins --from-file=plugins.yaml=plugins.yaml -o yaml --dry-run=client | kubectl replace configmap -f -

.PHONY: update-prow-job-config
update-prow-job-config:
	kubectl create configmap -n prow job-config --from-file=sig-windows-networking.yaml=jobs/sig-windows-networking.yaml -o yaml --dry-run=client | kubectl replace configmap -f -

.PHONY: buildx-prow-backup
buildx-prow-backup:
	docker buildx build \
		--progress=plain --no-cache --pull --platform linux/amd64 --output=type=registry \
		-t $(REGISTRY)/prow-backup:dev \
		./backup
