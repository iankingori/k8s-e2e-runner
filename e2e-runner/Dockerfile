FROM ubuntu:20.04

ARG GO_VERSION=1.15.7
ARG TF_VERSION=0.12.24
ARG CAPI_VERSION=v0.3.8
ARG KUBECTL_VERSION=v1.20.2

# Install system APT packages & dependencies
RUN apt-get update && \
    apt-get install -y \
        build-essential curl git libffi-dev libssl-dev \
        python3 python3-pip rsync unzip wget net-tools openssh-client vim

# Install google-cloud-sdk from the Google Cloud APT PPA
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add - && \
    apt-get update && \
    apt-get install -y google-cloud-sdk

# APT cleanup
RUN apt-get autoclean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/*

# Install Python tools
RUN pip3 install \
        configargparse sh property-cached \
        ansible==2.9.13 pywinrm==0.4.1 \
        azure-common==1.1.25 azure-mgmt-resource==10.2.0 \
        azure-mgmt-compute==13.1.0 azure-mgmt-network==11.0.0

# Install Golang
ENV GOPATH "/go"
ENV PATH "$PATH:/usr/local/go/bin:$GOPATH/bin"
RUN curl -O https://dl.google.com/go/go${GO_VERSION}.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz && \
    rm go${GO_VERSION}.linux-amd64.tar.gz && \
    mkdir -p "${GOPATH}/src"

# Install terraform
RUN wget -q https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip && \
    unzip terraform_${TF_VERSION}_linux_amd64.zip && \
    rm terraform_${TF_VERSION}_linux_amd64.zip && \
    mv terraform /usr/local/bin

# Install clusterctl
RUN curl -Lo /usr/local/bin/clusterctl "https://github.com/kubernetes-sigs/cluster-api/releases/download/${CAPI_VERSION}/clusterctl-linux-amd64" && \
    chmod +x /usr/local/bin/clusterctl

# Install kubectl
RUN curl -Lo /usr/local/bin/kubectl "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    chmod +x /usr/local/bin/kubectl
ENV KUBECTL_PATH "/usr/local/bin/kubectl"

WORKDIR /workspace

ADD bootstrap.py /workspace
RUN chmod +x bootstrap.py

ENTRYPOINT ["./bootstrap.py"]
