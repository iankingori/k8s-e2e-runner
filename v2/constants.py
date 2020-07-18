AZURE_LOCATIONS = ["eastus2", "westeurope", "westus2", "southcentralus"]
WINDOWS_ADMIN_USER = "azureuser"

FLANNEL_MODE_OVERLAY = "overlay"
FLANNEL_MODE_L2BRIDGE = "host-gw"

KUBERNETES_LINUX_BINS_LOCATION = "_output/local/bin/linux/amd64/"
KUBERNETES_WINDOWS_BINS_LOCATION = "_output/local/bin/windows/amd64"
KUBERNETES_IMAGES_LOCATION = "_output/release-images/amd64"

SDN_BINS_LOCATION = "out"
CONTAINERD_BINS_LOCATION = "_output"
CONTAINERD_SHIM_DIR = "./cmd/containerd-shim-runhcs-v1"
CONTAINERD_SHIM_BIN = "containerd-shim-runhcs-v1.exe"
CONTAINERD_CTR_LOCATION = "bin/ctr.exe"
