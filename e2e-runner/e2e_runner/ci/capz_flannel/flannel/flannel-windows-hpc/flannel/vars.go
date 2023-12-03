package flannel

import (
	"os"
	"path/filepath"
)

var (
	ControlPlaneCIDR = os.Getenv("CONTROL_PLANE_CIDR")
	NodeCIDR         = os.Getenv("NODE_CIDR")
	ServiceSubnet    = os.Getenv("SERVICE_SUBNET")
	PodSubnet        = os.Getenv("POD_SUBNET")

	NetConfPath             = os.Getenv("FLANNEL_NET_CONF")
	CNIConfPath             = os.Getenv("FLANNEL_CNI_CONF")
	CNIBinDirPath           = filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "cni/bin")
	ContainerdCNIBinDirPath = os.Getenv("CONTAINERD_CNI_BIN_DIR")
)
