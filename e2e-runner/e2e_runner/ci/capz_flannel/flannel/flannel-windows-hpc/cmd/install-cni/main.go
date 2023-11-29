package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"path/filepath"

	"flannel-windows/flannel"
	"flannel-windows/utils"

	"github.com/Microsoft/hcsshim/hcn"
	"github.com/Microsoft/windows-container-networking/cni"
	"github.com/flannel-io/flannel/pkg/ip"
	"github.com/flannel-io/flannel/pkg/subnet"
)

const (
	BuildCNIBinDirPath = "/build/cni/bin"
)

func getFlannelNetConf() (*subnet.Config, error) {
	bytes, err := os.ReadFile(flannel.NetConfPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read flannel net config: %v", err)
	}
	netConf, err := subnet.ParseConfig(string(bytes))
	if err != nil {
		return nil, fmt.Errorf("failed to parse flannel net config: %v", err)
	}
	return netConf, nil
}

func getDefaultIPNet() (*net.IPNet, error) {
	iface, err := ip.GetDefaultGatewayInterface()
	if err != nil {
		return nil, err
	}
	addrs, err := iface.Addrs()
	if err != nil {
		return nil, err
	}
	for _, addr := range addrs {
		if ip, ok := addr.(*net.IPNet); ok {
			if ip.IP.To4() != nil {
				return ip, nil
			}
		}
	}
	return nil, fmt.Errorf("no IPv4 address found for default interface")
}

func getOutboundNATPolicyKVP() (*cni.KVP, error) {
	exceptions := []string{
		flannel.ServiceSubnet,
		flannel.PodSubnet,
	}
	flannelNetConf, err := getFlannelNetConf()
	if err != nil {
		return nil, err
	}
	if flannelNetConf.BackendType == "host-gw" {
		exceptions = append(exceptions, flannel.ControlPlaneCIDR)
		exceptions = append(exceptions, flannel.NodeCIDR)
	}
	settings := hcn.OutboundNatPolicySetting{
		Exceptions: exceptions,
	}
	rawJSON, err := json.Marshal(settings)
	if err != nil {
		return nil, err
	}
	policy := hcn.EndpointPolicy{
		Type:     hcn.OutBoundNAT,
		Settings: rawJSON,
	}
	rawJSON, err = json.Marshal(policy)
	if err != nil {
		return nil, err
	}
	kvp := cni.KVP{
		Name:  "EndpointPolicy",
		Value: rawJSON,
	}
	return &kvp, nil
}

func getServiceSubnetSDNRouteKVP() (*cni.KVP, error) {
	settings := hcn.SDNRoutePolicySetting{
		DestinationPrefix: flannel.ServiceSubnet,
		NeedEncap:         true,
	}
	rawJSON, err := json.Marshal(settings)
	if err != nil {
		return nil, err
	}
	policy := hcn.EndpointPolicy{
		Type:     hcn.SDNRoute,
		Settings: rawJSON,
	}
	rawJSON, err = json.Marshal(policy)
	if err != nil {
		return nil, err
	}
	kvp := cni.KVP{
		Name:  "EndpointPolicy",
		Value: rawJSON,
	}
	return &kvp, nil
}

func getNodeSubnetSDNRouteKVP() (*cni.KVP, error) {
	defaultIPNet, err := getDefaultIPNet()
	if err != nil {
		return nil, err
	}
	defaultNetmaskLength, _ := defaultIPNet.Mask.Size()
	settings := hcn.SDNRoutePolicySetting{
		DestinationPrefix: fmt.Sprintf("%s/%d", defaultIPNet.IP, defaultNetmaskLength),
		NeedEncap:         true,
	}
	rawJSON, err := json.Marshal(settings)
	if err != nil {
		return nil, err
	}
	policy := hcn.EndpointPolicy{
		Type:     hcn.SDNRoute,
		Settings: rawJSON,
	}
	rawJSON, err = json.Marshal(policy)
	if err != nil {
		return nil, err
	}
	kvp := cni.KVP{
		Name:  "EndpointPolicy",
		Value: rawJSON,
	}
	return &kvp, nil
}

func getNodeProviderAddressKVP() (*cni.KVP, error) {
	defaultIPNet, err := getDefaultIPNet()
	if err != nil {
		return nil, err
	}
	settings := hcn.ProviderAddressEndpointPolicySetting{
		ProviderAddress: defaultIPNet.IP.String(),
	}
	rawJSON, err := json.Marshal(settings)
	if err != nil {
		return nil, err
	}
	policy := hcn.EndpointPolicy{
		Type:     hcn.NetworkProviderAddress,
		Settings: rawJSON,
	}
	rawJSON, err = json.Marshal(policy)
	if err != nil {
		return nil, err
	}
	kvp := cni.KVP{
		Name:  "EndpointPolicy",
		Value: rawJSON,
	}
	return &kvp, nil
}

func getCNIConfAdditionalArgs() ([]cni.KVP, error) {
	additionalArgs := []cni.KVP{}
	// Append OutBoundNAT policy
	outboundNATKVP, err := getOutboundNATPolicyKVP()
	if err != nil {
		return additionalArgs, err
	}
	additionalArgs = append(additionalArgs, *outboundNATKVP)
	// Append SDNRoute policy for service subnet
	serviceSubnetSDNRouteKVP, err := getServiceSubnetSDNRouteKVP()
	if err != nil {
		return additionalArgs, err
	}
	additionalArgs = append(additionalArgs, *serviceSubnetSDNRouteKVP)
	// host-gw - Append SDNRoute policy for node subnet
	// vxlan - Append ProviderAddress policy for node address
	flannelNetConf, err := getFlannelNetConf()
	if err != nil {
		return additionalArgs, err
	}
	if flannelNetConf.BackendType == "host-gw" {
		nodeSubnetSDNRouteKVP, err := getNodeSubnetSDNRouteKVP()
		if err != nil {
			return additionalArgs, err
		}
		additionalArgs = append(additionalArgs, *nodeSubnetSDNRouteKVP)
	} else if flannelNetConf.BackendType == "vxlan" {
		nodeProviderAddressKVP, err := getNodeProviderAddressKVP()
		if err != nil {
			return additionalArgs, err
		}
		additionalArgs = append(additionalArgs, *nodeProviderAddressKVP)
	}
	return additionalArgs, nil
}

func createCNIConf() error {
	if _, err := os.Stat(flannel.CNIConfPath); err == nil {
		log.Println("CNI config already exists")
		return nil
	}
	flannelNetConf, err := getFlannelNetConf()
	if err != nil {
		return err
	}
	cniConf := flannel.NetConf{}
	cniConf.CNIVersion = "0.3.0"
	cniConf.Type = "flannel"
	cniConf.Capabilities = map[string]bool{
		"portMappings": true,
		"dns":          true,
	}
	if flannelNetConf.BackendType == "host-gw" {
		cniConf.Name = "cbr0"
		cniConf.Delegate.Type = "sdnbridge"
		cniConf.Delegate.OptionalFlags = map[string]bool{
			"forceBridgeGateway": true,
		}
	} else if flannelNetConf.BackendType == "vxlan" {
		cniConf.Name = "flannel.4096"
		cniConf.Delegate.Type = "sdnoverlay"
	}
	additionalArgs, err := getCNIConfAdditionalArgs()
	if err != nil {
		return err
	}
	cniConf.Delegate.AdditionalArgs = additionalArgs
	bytes, err := json.MarshalIndent(cniConf, "", "  ")
	if err != nil {
		return err
	}
	log.Printf("creating CNI config %s", flannel.CNIConfPath)
	cniConfDir := filepath.Dir(flannel.CNIConfPath)
	if err := os.MkdirAll(cniConfDir, os.ModeDir); err != nil {
		return fmt.Errorf("failed to create CNI directory %s: %v", cniConfDir, err)
	}
	if err := os.WriteFile(flannel.CNIConfPath, bytes, 0644); err != nil {
		return err
	}
	return nil
}

func copyCNIBinaries() error {
	if flannel.ContainerdCNIBinDirPath == "" {
		return fmt.Errorf("CONTAINERD_CNI_BIN_DIR environment variable is not set")
	}
	if err := os.MkdirAll(flannel.ContainerdCNIBinDirPath, os.ModeDir); err != nil {
		return fmt.Errorf("failed to create containerd CNI directory %s: %v", flannel.ContainerdCNIBinDirPath, err)
	}
	// copy CNI binaries
	if err := utils.CopyFiles(flannel.CNIBinDirPath, flannel.ContainerdCNIBinDirPath); err != nil {
		return fmt.Errorf("failed to copy cni binaries: %v", err)
	}
	// copy CI CNI binaries (if present)
	if _, err := os.Stat(BuildCNIBinDirPath); !os.IsNotExist(err) {
		if err := utils.CopyFiles(BuildCNIBinDirPath, flannel.ContainerdCNIBinDirPath); err != nil {
			return fmt.Errorf("failed to copy cni CI/CD binaries: %v", err)
		}
	}
	return nil
}

func main() {
	// copy CNI binaries
	if err := copyCNIBinaries(); err != nil {
		panic(fmt.Errorf("failed to copy CNI binaries: %v", err))
	}
	// create flannel CNI config file on the host
	if err := createCNIConf(); err != nil {
		panic(fmt.Errorf("failed to create CNI config file: %v", err))
	}
}
