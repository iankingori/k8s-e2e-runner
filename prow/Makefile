
all: update-configs


create-config:
	kubectl create configmap -n prow config --from-file=config.yaml=config.yaml

create-plugins:
	kubectl create configmap -n prow plugins --from-file=plugins.yaml=plugins.yaml

create-job-config:
	kubectl create configmap -n prow job-config --from-file=sig-windows-networking.yaml=jobs/sig-windows-networking.yaml

.PHONY: create-config create-plugins create-job-config

create-configs: create-config create-plugins create-job-config


update-config:
	kubectl create configmap -n prow config --from-file=config.yaml=config.yaml -o yaml --dry-run=client | kubectl replace configmap -n prow config -f -

update-plugins:
	kubectl create configmap -n prow plugins --from-file=plugins.yaml=plugins.yaml -o yaml --dry-run=client | kubectl replace configmap -n prow plugins -f -

update-job-config:
	kubectl create configmap -n prow job-config --from-file=sig-windows-networking.yaml=jobs/sig-windows-networking.yaml -o yaml --dry-run=client | kubectl replace configmap -n prow plugins -f -

.PHONY: update-config update-plugins update-job-config

update-configs: update-config update-plugins update-job-config
