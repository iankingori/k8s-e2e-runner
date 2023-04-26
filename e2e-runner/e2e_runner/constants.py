AZURE_LOCATIONS = [
    "canadacentral",
    "centralus",
    "eastus",
    "eastus2",
    "northeurope",
    "southcentralus",
    "uksouth",
    "westeurope",
    "westus2",
]

COMPUTE_QUOTAS = [
    "virtualMachines",
    "cores",
    "standardDSv3Family",
    "PremiumDiskCount",
]
NETWORK_QUOTAS = [
    "VirtualNetworks",
    "NetworkInterfaces"
    "NetworkSecurityGroups",
    "LoadBalancers",
    "PublicIPAddresses",
    "RouteTables",
]

DEFAULT_KUBERNETES_VERSION = "v1.27.1"
DEFAULT_AKS_VERSION = "1.24"

FLANNEL_MODE_OVERLAY = "overlay"
FLANNEL_MODE_L2BRIDGE = "host-gw"
