FROM ubuntu:22.04

ARG CAPI_VERSION=v1.1.3
ARG KUBECTL_VERSION=v1.23.6

# Install system APT packages & dependencies
RUN apt-get update && \
    apt-get install -y \
        curl git python3 python3-pip openssh-client rsync net-tools vim

# APT cleanup
RUN apt-get autoclean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
ADD requirements.txt /tmp
RUN pip3 install -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Install clusterctl
RUN curl -Lo /usr/local/bin/clusterctl "https://github.com/kubernetes-sigs/cluster-api/releases/download/${CAPI_VERSION}/clusterctl-linux-amd64" && \
    chmod +x /usr/local/bin/clusterctl

# Install kubectl
RUN curl -Lo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    chmod +x /usr/local/bin/kubectl
ENV KUBECTL_PATH "/usr/local/bin/kubectl"

WORKDIR /workspace

ADD cleanup-azure-rgs.py /workspace
RUN chmod +x cleanup-azure-rgs.py

ADD entrypoint.sh /workspace
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/workspace/entrypoint.sh"]
