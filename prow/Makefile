
all: update-configs


create-config:
	kubectl create configmap config --from-file=config.yaml=config.yaml

create-plugins:
	kubectl create configmap plugins --from-file=plugins.yaml=plugins.yaml

create-job-config:
	kubectl create configmap job-config --from-file=sig-windows-networking.yaml=jobs/sig-windows-networking.yaml

.PHONY: create-config create-plugins create-job-config

create-configs: create-config create-plugins create-job-config


update-config:
	kubectl create configmap config --from-file=config.yaml=config.yaml -o yaml --dry-run=client | kubectl replace configmap config -f -

update-plugins:
	kubectl create configmap plugins --from-file=plugins.yaml=plugins.yaml -o yaml --dry-run=client | kubectl replace configmap plugins -f -

update-job-config:
	kubectl create configmap job-config --from-file=sig-windows-networking.yaml=jobs/sig-windows-networking.yaml -o yaml --dry-run=client | kubectl replace configmap plugins -f -

.PHONY: update-config update-plugins update-job-config

update-configs: update-config update-plugins update-job-config
