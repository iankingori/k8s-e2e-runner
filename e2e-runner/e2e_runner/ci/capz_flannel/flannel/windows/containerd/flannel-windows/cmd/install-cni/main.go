package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"

	"flannel-windows/types"
	"flannel-windows/utils"

	"github.com/Microsoft/hcsshim/hcn"
	"github.com/Microsoft/windows-container-networking/cni"
	"github.com/flannel-io/flannel/pkg/ip"
	"github.com/flannel-io/flannel/subnet"
	"gopkg.in/yaml.v3"
)

func getKubeadmConfig() (*types.KubeadmConfig, error) {
	bytes, err := os.ReadFile(filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "etc/kubeadm-config/ClusterConfiguration"))
	if err != nil {
		return nil, err
	}
	cfg := types.KubeadmConfig{}
	if err := yaml.Unmarshal(bytes, &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

func getFlannelNetConf() (*subnet.Config, error) {
	bytes, err := os.ReadFile(filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "etc/kube-flannel/net-conf.json"))
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
	return nil, fmt.Errorf("No IPv4 address found for default interface")
}

func getOutboundNATPolicyKVP() (*cni.KVP, error) {
	kubeadmConfig, err := getKubeadmConfig()
	if err != nil {
		return nil, err
	}
	exceptions := []string{
		kubeadmConfig.Networking.ServiceSubnet,
		kubeadmConfig.Networking.PodSubnet,
	}
	flannelNetConf, err := getFlannelNetConf()
	if err != nil {
		panic(fmt.Errorf("failed to get flannel net config: %v", err))
	}
	if flannelNetConf.BackendType == "host-gw" {
		exceptions = append(exceptions, os.Getenv("CONTROL_PLANE_CIDR"))
		exceptions = append(exceptions, os.Getenv("NODE_CIDR"))
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
	kubeadmConfig, err := getKubeadmConfig()
	if err != nil {
		return nil, err
	}
	settings := hcn.SDNRoutePolicySetting{
		DestinationPrefix: kubeadmConfig.Networking.ServiceSubnet,
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
	cniConfFile := "/etc/cni/net.d/10-flannel.conf"
	if _, err := os.Stat(cniConfFile); err == nil {
		fmt.Println("cni config already exists")
		return nil
	}
	bytes, err := os.ReadFile(filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "/etc/kube-flannel-windows/cni-conf.json"))
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
	fmt.Printf("create CNI config %s\n", cniConfFile)
	if err := os.WriteFile(cniConfFile, bytes, 0644); err != nil {
		return err
	}
	return nil
}

func main() {
	// create flannel directories on the host
	dirs := []string{
		"/etc/kube-flannel",
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
	if err := utils.CopyFiles(filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "cni/bin"), "/opt/cni/bin"); err != nil {
		panic(fmt.Errorf("failed to copy cni binaries: %v", err))
	}
	// copy CI CNI binaries (if present)
	if err := utils.CopyFiles("/build/cni/bin", "/opt/cni/bin"); err != nil {
		panic(fmt.Errorf("failed to copy cni CI binaries: %v", err))
	}
	// copy flannel net-conf
	if err := utils.CopyFile(filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "etc/kube-flannel/net-conf.json"), "/etc/kube-flannel/net-conf.json"); err != nil {
		panic(fmt.Errorf("failed to copy flannel net-conf: %v", err))
	}
	// create flannel CNI config file on the host
	if err := createCNIConf(); err != nil {
		panic(fmt.Errorf("failed to create CNI config file: %v", err))
	}
}
