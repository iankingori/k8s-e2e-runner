FROM e2eteam/dind-bionic:latest

ARG GO_VERSION=1.15
ARG TF_VERSION=0.12.24
ARG KIND_VERSION=v0.8.1
ARG CAPI_VERSION=v0.3.8

# Install system packages
RUN apt-get update && \
    apt-get install -y \
        build-essential curl git libffi-dev libssl-dev \
        python3 python3-pip rsync unzip wget net-tools openssh-client vim

# Setup UTC timezone
RUN ln -fs /usr/share/zoneinfo/UTC /etc/localtime && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata

# APT cleanup
RUN apt-get autoclean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/*

# Install Python tools
RUN pip3 install --upgrade \
        pip setuptools \
        crudini toml configargparse pycrypto sh property-cached \
        python-novaclient python-openstackclient \
        ansible pywinrm \
        azure-common azure-mgmt-resource azure-mgmt-compute azure-mgmt-network

# Install Golang
ENV GOPATH "/go"
ENV PATH "$PATH:/usr/local/go/bin:$GOPATH/bin"

RUN curl -O https://dl.google.com/go/go${GO_VERSION}.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz && \
    rm go${GO_VERSION}.linux-amd64.tar.gz && \
    mkdir -p "${GOPATH}/src"

# Install gcloud cli
ENV PATH=/google-cloud-sdk/bin:/workspace:${PATH} \
    CLOUDSDK_CORE_DISABLE_PROMPTS=1

RUN wget -q https://dl.google.com/dl/cloudsdk/channels/rapid/google-cloud-sdk.tar.gz && \
    tar xzf google-cloud-sdk.tar.gz -C / && \
    rm google-cloud-sdk.tar.gz && \
    /google-cloud-sdk/install.sh \
        --disable-installation-options \
        --bash-completion=false \
        --path-update=false \
        --usage-reporting=false && \
    gcloud components install alpha beta && \
    gcloud info | tee /gcloud-info.txt

# Install terraform
RUN wget -q https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip && \
    unzip terraform_${TF_VERSION}_linux_amd64.zip && \
    rm terraform_${TF_VERSION}_linux_amd64.zip && \
    mv terraform /usr/local/bin

# Install kind
RUN curl -Lo /usr/local/bin/kind "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-amd64" && \
    chmod +x /usr/local/bin/kind

# Install clusterctl
RUN curl -Lo /usr/local/bin/clusterctl "https://github.com/kubernetes-sigs/cluster-api/releases/download/${CAPI_VERSION}/clusterctl-linux-amd64" && \
    chmod +x /usr/local/bin/clusterctl

WORKDIR /workspace

ADD bootstrap.py /workspace
RUN chmod +x bootstrap.py

ENTRYPOINT ["/usr/local/bin/tini", "--", "/entrypoint.sh", "./bootstrap.py"]
