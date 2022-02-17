package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"flannel-windows/utils"
)

func main() {
	utils.CopyFile(
		filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "flannel-config-file/kubeconfig.conf"),
		filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "kubeconfig.conf"),
	)
	fmt.Printf("POD_NAME: %s\n", os.Getenv("POD_NAME"))
	fmt.Printf("POD_NAMESPACE: %s\n", os.Getenv("POD_NAMESPACE"))
	cmd := exec.Command(
		filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "flannel/flanneld.exe"),
		"--kubeconfig-file", filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "kubeconfig.conf"),
		"--kube-subnet-mgr",
		"--ip-masq",
		"--iface", os.Getenv("HOST_IP"))
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		panic(fmt.Errorf("error running flanneld: %v", err))
	}
}
