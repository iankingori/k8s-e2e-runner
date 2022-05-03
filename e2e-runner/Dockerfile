FROM ubuntu:20.04

ARG CAPI_VERSION=v1.1.3
ARG KUBECTL_VERSION=v1.23.6

# Install system APT packages & dependencies
RUN apt-get update && \
    apt-get install -y \
        build-essential curl git libffi-dev libssl-dev \
        python3 python3-pip rsync unzip wget net-tools openssh-client vim

# APT cleanup
RUN apt-get autoclean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
ADD requirements.txt /tmp
RUN pip3 install -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Install Golang
ENV GOPATH "/home/prow/go"
ENV PATH "$PATH:/usr/local/go/bin:$GOPATH/bin"
RUN GO_VERSION=$(curl -s -L https://golang.org/VERSION\?m\=text) && \
    curl -O https://dl.google.com/go/${GO_VERSION}.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf ${GO_VERSION}.linux-amd64.tar.gz && \
    rm ${GO_VERSION}.linux-amd64.tar.gz && \
    mkdir -p $GOPATH && \
    go version

# Install clusterctl
RUN curl -Lo /usr/local/bin/clusterctl "https://github.com/kubernetes-sigs/cluster-api/releases/download/${CAPI_VERSION}/clusterctl-linux-amd64" && \
    chmod +x /usr/local/bin/clusterctl

# Install kubectl
RUN curl -Lo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    chmod +x /usr/local/bin/kubectl
ENV KUBECTL_PATH "/usr/local/bin/kubectl"

WORKDIR /workspace

ADD cleanup-azure-rgs.py /workspace
ADD entrypoint.sh /workspace
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/workspace/entrypoint.sh"]
