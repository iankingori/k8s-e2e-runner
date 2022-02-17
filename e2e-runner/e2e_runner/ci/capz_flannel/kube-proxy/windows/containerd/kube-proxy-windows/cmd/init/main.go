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

	"github.com/Microsoft/hcsshim/hcn"
	"gopkg.in/yaml.v3"
)

var (
	cniBinDir         string = "/opt/cni/bin"
	cniConfFile       string = "/etc/cni/net.d/10-flannel.conf"
	kubeProxyDir      string = "/var/lib/kube-proxy"
	kubeProxyConfFile string = filepath.Join(kubeProxyDir, "config.conf")
	sourceVipDir      string = "/sourceVip"
	sourceVipFile     string = filepath.Join(sourceVipDir, "sourceVip.json")
)

func parseSourceVipFile() (*types.SourceVip, error) {
	bytes, err := os.ReadFile(sourceVipFile)
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
	if _, err := os.Stat(cniConfFile); os.IsNotExist(err) {
		return nil, fmt.Errorf("cni conf file (%s) does not exist", cniConfFile)
	}
	bytes, err := os.ReadFile(cniConfFile)
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
	if err := os.MkdirAll(sourceVipDir, os.ModeDir); err != nil {
		return "", err
	}
	if _, err := os.Stat(sourceVipFile); err == nil {
		sourceVip, err := parseSourceVipFile()
		if err != nil {
			return "", err
		}
		return strings.Split(sourceVip.IP4.IP, "/")[0], nil
	}
	ipamPluginBin := filepath.Join(cniBinDir, "host-local.exe")
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
	os.Setenv("CNI_PATH", cniBinDir)
	cmd := exec.Command(ipamPluginBin)
	cmd.Stdin = strings.NewReader(ipamConfig)
	out, err := cmd.Output()
	if err != nil {
		fmt.Printf("Command output: %s\n", out)
		panic(fmt.Errorf("error running host-local.exe ipam plugin: %v", err))
	}
	if err := os.WriteFile(sourceVipFile, out, 0644); err != nil {
		return "", err
	}
	sourceVip, err := parseSourceVipFile()
	if err != nil {
		return "", err
	}
	return strings.Split(sourceVip.IP4.IP, "/")[0], nil
}

func createKubeProxyConfig() error {
	fmt.Printf("create %s file\n", kubeProxyConfFile)
	bytes, err := os.ReadFile(filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "var/lib/kube-proxy/config.conf"))
	if err != nil {
		return err
	}
	data := make(map[string]interface{})
	if err := yaml.Unmarshal(bytes, &data); err != nil {
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
	winkernel := data["winkernel"].(map[string]interface{})
	winkernel["networkName"] = network.Name
	winkernel["enableDSR"] = enableDSR
	featureGates := make(map[string]bool)
	featureGates["WinDSR"] = enableDSR
	if network.Type == hcn.Overlay {
		sourceVip, err := getSourceVip()
		if err != nil {
			return err
		}
		winkernel["sourceVip"] = sourceVip
		featureGates["WinOverlay"] = true
	}
	data["mode"] = "kernelspace"
	data["winkernel"] = winkernel
	data["featureGates"] = featureGates
	yamlBytes, err := yaml.Marshal(data)
	if err != nil {
		return err
	}
	if err := os.WriteFile(kubeProxyConfFile, yamlBytes, 0644); err != nil {
		return err
	}
	return nil
}

func main() {
	fmt.Printf("create %s dir\n", kubeProxyDir)
	if err := os.MkdirAll(kubeProxyDir, os.ModeDir); err != nil {
		panic(fmt.Errorf("error creating kube-proxy dir: %v", err))
	}
	if err := createKubeProxyConfig(); err != nil {
		panic(fmt.Errorf("error creating kube-proxy config: %v", err))
	}
}
