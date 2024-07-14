package kube_proxy

import (
	"os"
	"path/filepath"
)

var (
	CNIBinDir = filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "cni/bin")

	HnsNetworkName        = os.Getenv("HNS_NETWORK_NAME")
	CNIVersion            = os.Getenv("CNI_VERSION")
	ConfFile              = os.Getenv("KUBE_PROXY_CONF")
	WindowsConfFile       = os.Getenv("KUBE_PROXY_WINDOWS_CONF")
	WindowsKubeconfigFile = filepath.Join(filepath.Dir(WindowsConfFile), "kubeconfig.conf")
	SourceVipFile         = filepath.Join(filepath.Dir(WindowsConfFile), "sourceVip.json")
)
