# Kubernetes Azure Windows images with cloudbase-init

This directory contains the scripts and config files needed to generate Azure custom images with cloudbase-init to be used for the Kubernetes workers.

The scripts and config files are based on the automation from [cloudbase/windows-openstack-imaging-tools](https://github.com/cloudbase/windows-openstack-imaging-tools).


## How to generate the images

### Requirements

* Windows machine with Hyper-V role enabled (including the PowerShell management modules)
* ISO file with the operating system used for the custom image downloaded locally. Supported operating systems by the scripts in this directory:
    * Windows Server 2019, Long-Term Servicing Channel (LTSC)
    * Windows Server 1909, Semi-Annual Channel (SAC)
    * Windows Server 2004, Semi-Annual Channel (SAC)
* Git installed (needed to clone the imaging tools repository)

### Windows images configurations

The current scripts allows to prepare the following configurations for the K8s Windows workers:

* Windows Server 2019 LTSC with Docker runtime
* Windows Server 2019 LTSC with Containerd runtime
* Windows Server 1909 SAC with Containerd runtime
* Windows Server 2004 SAC with Containerd runtime

### Steps

1. Clone the [cloudbase/windows-openstack-imaging-tools](https://github.com/cloudbase/windows-openstack-imaging-tools) repository:
    ```
    git clone https://github.com/cloudbase/windows-openstack-imaging-tools <IMAGING_TOOLS_DIR>
    ```

2. Open PowerShell as Administrator and import the module:
    ```
    Import-Module <IMAGING_TOOLS_DIR>\WinImageBuilder.psm1
    ```

3. Mount ISO file and note the mount drive letter as it's needed later:
    ```
    Mount-DiskImage E:\ISO\en_windows_server_2019.iso | Get-Volume | select DriveLetter

    DriveLetter
    -----------
              F
    ```

4. Choose the desired K8s Windows worker `ini` configuration file. For this example, we choose `azure-ws-ltsc2019-containerd.ini`)

5. Adjust the following values in the config file to correspond to your environment:

    * `wim_file_path=F:\Sources\install.wim`, make sure this path starts with the ISO drive letter previously mounted
    * `image_path`, the absolute path for the destination `vhdx`
    * `custom_resources_path` and `custom_scripts_path`, replace base path `D:\capi-azure-image` with the current directory (`<K8S_E2E_RUNNER_DIR>/images-builder/azure-cbsl-init`)
    * `cloudbase_init_config_path` and `cloudbase_init_unattended_config_path`, replace `D:\windows-openstack-imaging-tools` with the `<IMAGING_TOOLS_DIR>` used previously to clone the imaging tools directory

    NOTE: If you want to change the `kubelet` and `kubeadm` versions from the image, you need to change `-KubernetesVersion v1.18.8` from `<K8S_E2E_RUNNER_DIR>/images-builder/azure-cbsl-init/CustomScripts/containerd/RunBeforeCloudbaseInitInstall.ps1`.

6. Generate the worker image and wait for it to finish (it may take a while):
    ```
    New-WindowsOnlineImage -ConfigFilePath azure-ws-ltsc2019-containerd.ini
    ```

7. When the image generation finished, we need to convert it from `vhdx` to fixed `vhd`, and make sure its size is a multiple of `1MB` (required to be used as Azure custom image). Given the `vhdx` file, you can do this via:
    ```
    $vhdxFile = "D:\images\azure-ws-ltsc2019-containerd-cbsl-init.vhdx"
    $vhdFile = "D:\images\azure-ws-ltsc2019-containerd-cbsl-init.vhd"

    Convert-VHD -Path $vhdxFile -DestinationPath $vhdFile -VHDType Fixed

    $newSize = [math]::ceiling((Get-VHD $vhdPath).Size / 1MB) * 1MB
    Resize-VHD -Path $vhdFile -SizeBytes $newSize
    ```

8. Upload it to Azure, and publish it into a shared gallery to be consumed later on. Some useful resources on this topic are:
    * https://docs.microsoft.com/en-us/azure/virtual-machines/windows/sa-upload-generalized#upload-the-vhd
    * https://docs.microsoft.com/en-us/azure/virtual-machines/shared-images-cli
    * https://docs.microsoft.com/en-us/azure/virtual-machines/image-version-managed-image-cli
