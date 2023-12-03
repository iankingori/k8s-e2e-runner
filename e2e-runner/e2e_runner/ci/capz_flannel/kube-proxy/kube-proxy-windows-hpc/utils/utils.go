package utils

import (
	"fmt"
	"kube-proxy-windows/kube_proxy"

	"github.com/Microsoft/hcsshim/hcn"
)

func GetHnsNetwork() (*hcn.HostComputeNetwork, error) {
	networks, err := hcn.ListNetworks()
	if err != nil {
		return nil, err
	}
	if len(networks) == 0 {
		return nil, fmt.Errorf("no HNS networks found")
	}
	if len(networks) == 1 {
		return &networks[0], nil
	}
	if kube_proxy.HnsNetworkName == "" {
		return nil, fmt.Errorf("multiple HNS networks found, please specify the network name via HNS_NETWORK_NAME environment variable")
	}
	for _, network := range networks {
		if network.Name == kube_proxy.HnsNetworkName {
			return &network, nil
		}
	}
	return nil, fmt.Errorf("HNS network %s not found", kube_proxy.HnsNetworkName)
}
