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
    "westus3"
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

DEFAULT_KUBERNETES_VERSION = "v1.24.1"

FLANNEL_MODE_OVERLAY = "overlay"
FLANNEL_MODE_L2BRIDGE = "host-gw"
