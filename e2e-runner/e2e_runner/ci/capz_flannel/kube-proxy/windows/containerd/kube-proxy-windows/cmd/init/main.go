package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"kube-proxy-windows/types"
	"kube-proxy-windows/utils"

	"github.com/Microsoft/hcsshim/hcn"
	"k8s.io/kube-proxy/config/v1alpha1"
	"sigs.k8s.io/yaml"
)

var (
	kubeProxyConfPath = filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "var/lib/kube-proxy/config.conf")
	kubeconfigPath    = filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "var/lib/kube-proxy/kubeconfig.conf")
)

func parseSourceVipFile() (*types.SourceVip, error) {
	bytes, err := os.ReadFile(utils.SourceVipFile)
	if err != nil {
		return nil, err
	}
	sourceVip := types.SourceVip{}
	if err := json.Unmarshal(bytes, &sourceVip); err != nil {
		return nil, err
	}
	return &sourceVip, nil
}

func getHnsNetwork() (*hcn.HostComputeNetwork, error) {
	if _, err := os.Stat(utils.CNIConfFile); os.IsNotExist(err) {
		return nil, fmt.Errorf("cni conf file (%s) does not exist", utils.CNIConfFile)
	}
	bytes, err := os.ReadFile(utils.CNIConfFile)
	if err != nil {
		return nil, err
	}
	data := make(map[string]interface{})
	if err := json.Unmarshal(bytes, &data); err != nil {
		return nil, err
	}
	network, err := hcn.GetNetworkByName(data["name"].(string))
	if err != nil {
		return nil, err
	}
	return network, nil
}

func getSourceVip() (string, error) {
	if _, err := os.Stat(utils.SourceVipFile); err == nil {
		sourceVip, err := parseSourceVipFile()
		if err != nil {
			return "", err
		}
		return strings.Split(sourceVip.IP4.IP, "/")[0], nil
	}
	ipamPluginBin := filepath.Join(utils.CNIBinDir, "host-local.exe")
	if _, err := os.Stat(ipamPluginBin); os.IsNotExist(err) {
		return "", fmt.Errorf("ipam plugin binary (%s) does not exist", ipamPluginBin)
	}
	network, err := getHnsNetwork()
	if err != nil {
		return "", err
	}
	subnet := network.Ipams[0].Subnets[0].IpAddressPrefix
	ipamConfig := fmt.Sprintf(`
	{
		"cniVersion": "0.2.0",
		"name": "%s",
		"ipam": {
			"type": "host-local",
			"ranges": [
				[{"subnet": "%s"}]
			],
			"dataDir": "/var/lib/cni/networks"
		}
	}`, network.Name, subnet)
	os.Setenv("CNI_COMMAND", "ADD")
	os.Setenv("CNI_CONTAINERID", "SourceVip")
	os.Setenv("CNI_NETNS", "SourceVip")
	os.Setenv("CNI_IFNAME", "SourceVip")
	os.Setenv("CNI_PATH", utils.CNIBinDir)
	cmd := exec.Command(ipamPluginBin)
	cmd.Stdin = strings.NewReader(ipamConfig)
	out, err := cmd.Output()
	if err != nil {
		fmt.Printf("Command output: %s\n", out)
		panic(fmt.Errorf("error running host-local.exe ipam plugin: %v", err))
	}
	if err := os.WriteFile(utils.SourceVipFile, out, 0644); err != nil {
		return "", err
	}
	sourceVip, err := parseSourceVipFile()
	if err != nil {
		return "", err
	}
	return strings.Split(sourceVip.IP4.IP, "/")[0], nil
}

func createKubeProxyConfig() error {
	fmt.Printf("create %s file\n", utils.KubeProxyConfFile)

	bytes, err := os.ReadFile(kubeProxyConfPath)
	if err != nil {
		return err
	}
	cfg := v1alpha1.KubeProxyConfiguration{}
	if err := yaml.Unmarshal(bytes, &cfg); err != nil {
		return err
	}

	network, err := getHnsNetwork()
	if err != nil {
		return err
	}
	enableDSR, err := strconv.ParseBool(os.Getenv("ENABLE_WIN_DSR"))
	if err != nil {
		return err
	}

	cfg.Mode = "kernelspace"
	cfg.Winkernel.NetworkName = network.Name
	cfg.Winkernel.EnableDSR = enableDSR

	cfg.FeatureGates = make(map[string]bool)
	cfg.FeatureGates["WinDSR"] = enableDSR
	if network.Type == hcn.Overlay {
		sourceVip, err := getSourceVip()
		if err != nil {
			return err
		}
		cfg.Winkernel.SourceVip = sourceVip
		cfg.FeatureGates["WinOverlay"] = true
	}

	// TODO: remove this once containerd v1.7.0 is released, and bind volume mount behavior is used all the time.
	if err := utils.CopyFile(kubeconfigPath, utils.KubeconfigFile); err != nil {
		return err
	}
	cfg.ClientConnection.Kubeconfig = utils.KubeconfigFile

	yamlBytes, err := yaml.Marshal(cfg)
	if err != nil {
		return err
	}
	if err := os.WriteFile(utils.KubeProxyConfFile, yamlBytes, 0644); err != nil {
		return err
	}

	return nil
}

func main() {
	fmt.Printf("create %s dir\n", utils.KubeProxyDir)
	if err := os.MkdirAll(utils.KubeProxyDir, os.ModeDir); err != nil {
		panic(fmt.Errorf("error creating kube-proxy dir: %v", err))
	}
	if err := createKubeProxyConfig(); err != nil {
		panic(fmt.Errorf("error creating kube-proxy config: %v", err))
	}
}
