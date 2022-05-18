FROM ubuntu:20.04

ENV K8S_VERSION=v1.23.6
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
	apt-get install -y \
		curl \
		dateutils \
		jq \
		openssh-client && \
	rm -rf /var/lib/apt/lists/*

# Install kubernetes client
RUN curl -fsSL https://dl.k8s.io/${K8S_VERSION}/kubernetes-client-linux-amd64.tar.gz -o /tmp/k8s.tar.gz && \
	tar -zxf /tmp/k8s.tar.gz -C /tmp/ && \
	mv /tmp/kubernetes/client/bin/kubectl /usr/local/bin/kubectl && \
	rm -rf /tmp/k8s.tar.gz /tmp/kubernetes

# Install Azure CLI
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash

ADD backup.sh /usr/local/bin/backup.sh

RUN chmod +x /usr/local/bin/backup.sh

CMD /usr/local/bin/backup.sh
