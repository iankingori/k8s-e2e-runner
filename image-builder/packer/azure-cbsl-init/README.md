# Kubernetes Azure Windows images with cloudbase-init

This directory contains the scripts and config files needed to generate Azure custom images with cloudbase-init to be used for the Kubernetes workers.

## How to generate the images

### Requirements

* The `packer` tool installed. Download the latest binary for your platform from [here](https://www.packer.io/downloads).
* The `az` CLI tool installed.
  * An Azure Container Registry (ACR) must be setup to host the CI container images.

### Windows images configurations

The current scripts support the following K8s Windows workers configurations:

* Windows Server 2019 LTSC with Docker runtime
* Windows Server 2019 LTSC with Containerd runtime
* Windows Server 2004 SAC with Containerd runtime
* Windows Server 2022 LTSC with Containerd runtime

### Image builder steps

1. Export the necessary environment variables for the image builder:

    ```bash
    export AZURE_SUBSCRIPTION_ID="<SUBSCRIPTION_ID>"
    export AZURE_TENANT_ID="<TENANT_ID>"
    export AZURE_CLIENT_ID="<CLIENT_ID>"
    export AZURE_CLIENT_SECRET="<CLIENT_SECRET>"

    export RESOURCE_GROUP_NAME="<TARGET_RESOURCE_GROUP_NAME>"

    export ACR_NAME="<ACR_NAME>"
    export ACR_USER_NAME="<ACR_USER_NAME>"
    export ACR_USER_PASSWORD="<ACR_USER_PASSWORD>"

    export KUBERNETES_VERSION="v1.22.2"
    export FLANNEL_VERSION="v0.14.0"
    ```

2. Build the container images for the chosen K8s Windows worker configuration:

    ```bash
    BASE_IMAGE="mcr.microsoft.com/windows/servercore:ltsc2019"
    TAG="ltsc2019"

    az acr build --registry $ACR_NAME \
                 --image kube-proxy-windows:${KUBERNETES_VERSION}-windowsservercore-${TAG} \
                 --build-arg baseImage=${BASE_IMAGE} \
                 --build-arg k8sVersion=${KUBERNETES_VERSION} \
                 --platform windows \
                 --file e2e-runner/e2e_runner/ci/capz_flannel/kube-proxy/kube-proxy-windows.Dockerfile \
                 https://github.com/e2e-win/k8s-e2e-runner.git

    az acr build --registry $ACR_NAME \
                 --image flannel-windows:${FLANNEL_VERSION}-windowsservercore-${TAG} \
                 --build-arg baseImage=${BASE_IMAGE} \
                 --build-arg flannelVersion=${FLANNEL_VERSION} \
                 --platform windows \
                 --file e2e-runner/e2e_runner/ci/capz_flannel/flannel/kube-flannel-windows.Dockerfile \
                 https://github.com/e2e-win/k8s-e2e-runner.git
    ```

3. Run the packer image builder. Choose the variables file for the K8s worker image you want to build. You may want to adjust the variables from the variables file to match your environment:

    ```bash
    packer build -var-file=windows-ltsc2019-docker-variables.json windows.json
    ```

    When the `packer build` finishes, the resulted Azure managed image is ready to be used.

4. (Optional) Publish the managed image into a shared gallery, in case you want it to be used into multiple regions:

    ```bash
    IMAGE_ID="/subscriptions/<subscription ID>/resourceGroups/myResourceGroup/providers/Microsoft.Compute/images/myImage"

    az sig image-version create \
        --resource-group adtv-capz-win \
        --gallery-name capz_gallery \
        --gallery-image-definition ws-ltsc2019-containerd-cbsl-init \
        --gallery-image-version 2021.02.19 \
        --managed-image $IMAGE_ID \
        --target-regions westeurope eastus2 westus2 southcentralus \
        --replica-count 1
    ```
