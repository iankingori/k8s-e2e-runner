# Kubernetes Azure Windows images with cloudbase-init

This directory contains the scripts and config files needed to generate Azure custom images with cloudbase-init to be used for the Kubernetes workers.

## How to generate the images

### Requirements

* The `packer` tool installed. Download the latest binary for your platform from https://www.packer.io/downloads.

### Windows images configurations

The current scripts support the following K8s Windows workers configurations:

* Windows Server 2019 LTSC with Docker runtime
* Windows Server 2019 LTSC with Containerd runtime
* Windows Server 1909 SAC with Containerd runtime
* Windows Server 2004 SAC with Containerd runtime

### Image builder steps

1. Export the necessary environment variables for Packer:

    ```
    export AZURE_SUBSCRIPTION_ID="<SUBSCRIPTION_ID>"
    export AZURE_TENANT_ID="<TENANT_ID>"
    export AZURE_CLIENT_ID="<CLIENT_ID>"
    export AZURE_CLIENT_SECRET="<CLIENT_SECRET>"
    ```

2. Run the packer image builder. Choose the variables file for the K8s worker image you want to build. You may want to adjust the variables from the variables file to match your environment:

    ```
    packer build -var-file=windows-ltsc2019-docker-variables.json windows.json
    ```

    When the `packer build` finishes, the image will be published to the Azure shared image gallery given in the variables file.
