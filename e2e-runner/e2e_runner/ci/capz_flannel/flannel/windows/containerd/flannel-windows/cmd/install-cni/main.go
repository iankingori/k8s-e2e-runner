package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"

	"flannel-windows/utils"

	"github.com/Microsoft/hcsshim/hcn"
	"github.com/Microsoft/windows-container-networking/cni"
	"github.com/flannel-io/flannel/pkg/ip"
	"github.com/flannel-io/flannel/pkg/subnet"
)

func getFlannelNetConf() (*subnet.Config, error) {
	bytes, err := os.ReadFile(utils.KubeFlannelNetConfPath)
	if err != nil {
		return nil, err
	}
	netConf, err := subnet.ParseConfig(string(bytes))
	if err != nil {
		return nil, err
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
		utils.ServiceSubnet,
		utils.PodSubnet,
	}
	flannelNetConf, err := getFlannelNetConf()
	if err != nil {
		panic(fmt.Errorf("failed to get flannel net config: %v", err))
	}
	if flannelNetConf.BackendType == "host-gw" {
		exceptions = append(exceptions, utils.ControlPlaneCIDR)
		exceptions = append(exceptions, utils.NodeCIDR)
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
		DestinationPrefix: utils.ServiceSubnet,
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
		panic(fmt.Errorf("failed to get flannel net config: %v", err))
	}
	if flannelNetConf.BackendType == "host-gw" {
		nodeSubnetSDNRouteKVP, err := getNodeSubnetSDNRouteKVP()
		if err != nil {
			return additionalArgs, err
		}
		additionalArgs = append(additionalArgs, *nodeSubnetSDNRouteKVP)
	}
	if flannelNetConf.BackendType == "vxlan" {
		nodeProviderAddressKVP, err := getNodeProviderAddressKVP()
		if err != nil {
			return additionalArgs, err
		}
		additionalArgs = append(additionalArgs, *nodeProviderAddressKVP)
	}
	return additionalArgs, nil
}

func createCNIConf() error {
	if _, err := os.Stat(utils.CNIConfPath); err == nil {
		fmt.Println("cni config already exists")
		return nil
	}
	bytes, err := os.ReadFile(utils.KubeFlannelWindowsCniConfPath)
	if err != nil {
		return err
	}
	data := make(map[string]interface{})
	if err := json.Unmarshal(bytes, &data); err != nil {
		return err
	}
	cniConf := data["delegate"].(map[string]interface{})
	additionalArgs, err := getCNIConfAdditionalArgs()
	if err != nil {
		return err
	}
	cniConf["AdditionalArgs"] = additionalArgs
	data["delegate"] = cniConf
	bytes, err = json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	fmt.Printf("create CNI config %s\n", utils.CNIConfPath)
	if err := os.WriteFile(utils.CNIConfPath, bytes, 0644); err != nil {
		return err
	}
	return nil
}

func main() {
	// create flannel directories on the host
	dirs := []string{
		"/opt/cni/bin",
		"/etc/cni/net.d",
	}
	for _, dir := range dirs {
		fmt.Printf("create directory %s\n", dir)
		if err := os.MkdirAll(dir, os.ModeDir); err != nil {
			panic(fmt.Errorf("failed to create directory %s: %v", dir, err))
		}
	}
	// copy CNI binaries on the host
	if err := utils.CopyFiles(utils.CNIBinDirPath, "/opt/cni/bin"); err != nil {
		panic(fmt.Errorf("failed to copy cni binaries: %v", err))
	}
	// copy CI CNI binaries (if present)
	if err := utils.CopyFiles("/build/cni/bin", "/opt/cni/bin"); err != nil {
		panic(fmt.Errorf("failed to copy cni CI binaries: %v", err))
	}
	// create flannel CNI config file on the host
	if err := createCNIConf(); err != nil {
		panic(fmt.Errorf("failed to create CNI config file: %v", err))
	}
}
