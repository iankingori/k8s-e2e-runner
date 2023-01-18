package main

import (
	"flannel-windows/utils"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

var (
	flannelBinPath = filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "flannel/flanneld.exe")

	podName      = os.Getenv("POD_NAME")
	podNamespace = os.Getenv("POD_NAMESPACE")
	hostIP       = os.Getenv("HOST_IP")
)

// TODO: remove this once containerd v1.7.0 is released, and bind volume mount behavior is used all the time.
func fixInClusterConfig() {
	saDirPath := "/var/run/secrets/kubernetes.io/serviceaccount"
	containerSADirPath := filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), saDirPath)
	saFiles := []string{"ca.crt", "token"}

	if err := os.MkdirAll(saDirPath, os.ModeDir); err != nil {
		panic(fmt.Errorf("failed to create SA directory %s: %v", saDirPath, err))
	}

	for _, file := range saFiles {
		srcFile := filepath.Join(containerSADirPath, file)
		destFile := filepath.Join(saDirPath, file)

		if _, err := os.Stat(destFile); os.IsNotExist(err) {
			if err := utils.CopyFile(srcFile, destFile); err != nil {
				panic(fmt.Errorf("failed to copy file %s to %s: %v", srcFile, destFile, err))
			}
		}
	}
}

func main() {
	// TODO: remove this once containerd v1.7.0 is released, and bind volume mount behavior is used all the time.
	fixInClusterConfig()

	fmt.Printf("POD_NAME: %s\n", podName)
	fmt.Printf("POD_NAMESPACE: %s\n", podNamespace)
	cmd := exec.Command(
		flannelBinPath,
		"--kube-subnet-mgr",
		"--ip-masq",
		"--net-config-path", utils.KubeFlannelNetConfPath,
		"--iface", hostIP)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		panic(fmt.Errorf("error running flanneld: %v", err))
	}
}
