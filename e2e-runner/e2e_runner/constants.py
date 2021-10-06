AZURE_LOCATIONS = ["eastus2", "westeurope", "southcentralus"]

DEFAULT_KUBERNETES_VERSION = "v1.22.2"

SHARED_IMAGE_GALLERY_TYPE = "shared-image-gallery"
MANAGED_IMAGE_TYPE = "managed-image"

FLANNEL_MODE_OVERLAY = "overlay"
FLANNEL_MODE_L2BRIDGE = "host-gw"

KUBERNETES_LINUX_BINS_LOCATION = "_output/local/bin/linux/amd64"
KUBERNETES_WINDOWS_BINS_LOCATION = "_output/local/bin/windows/amd64"
KUBERNETES_IMAGES_LOCATION = "_output/release-images/amd64"

CONTAINERD_SHIM_DIR = "./cmd/containerd-shim-runhcs-v1"
CONTAINERD_SHIM_BIN = "containerd-shim-runhcs-v1.exe"

CAPI_VERSION = "v0.4.3"
CAPZ_PROVIDER_VERSION = "v0.5.2"
