package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"kube-proxy-windows/utils"
)

var (
	kubeProxyBinPath = filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "kube-proxy/kube-proxy.exe")

	nodeName     = os.Getenv("NODE_NAME")
	enableWinDSR = os.Getenv("ENABLE_WIN_DSR")
)

// TODO: remove this once containerd v1.7.0 is released, and bind volume mount behavior is used all the time.
func fixInClusterConfig() {
	saDirPath := "/var/run/secrets/kubernetes.io/serviceaccount"
	kubeProxySADirPath := filepath.Join(utils.KubeProxyDir, saDirPath)
	containerSADirPath := filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), saDirPath)
	saFiles := []string{"ca.crt", "token"}

	if err := os.MkdirAll(kubeProxySADirPath, os.ModeDir); err != nil {
		panic(fmt.Errorf("failed to create kube-proxy SA directory %s: %v", kubeProxySADirPath, err))
	}

	for _, file := range saFiles {
		saFilePath := filepath.Join(kubeProxySADirPath, file)
		if _, err := os.Stat(saFilePath); os.IsNotExist(err) {
			srcPath := filepath.Join(containerSADirPath, file)
			if err := utils.CopyFile(srcPath, saFilePath); err != nil {
				panic(fmt.Errorf("failed to copy file %s to %s: %v", srcPath, saFilePath, err))
			}
		}
	}
}

func main() {
	// TODO: remove this once containerd v1.7.0 is released, and bind volume mount behavior is used all the time.
	fixInClusterConfig()

	// copy CI binary (if present)
	buildBinary := "/build/kube-proxy.exe"
	if _, err := os.Stat(buildBinary); err == nil {
		fmt.Printf("kube-proxy build binary found (%s), using it", buildBinary)
		if err := utils.CopyFile(buildBinary, kubeProxyBinPath); err != nil {
			panic(fmt.Errorf("failed to copy file %s to %s: %v", buildBinary, kubeProxyBinPath, err))
		}
	}

	cmd := exec.Command(
		kubeProxyBinPath,
		fmt.Sprintf("--hostname-override=%s", nodeName),
		fmt.Sprintf("--enable-dsr=%s", enableWinDSR),
		fmt.Sprintf("--config=%s", utils.KubeProxyConfFile),
		"--v=4",
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		panic(fmt.Errorf("error running kube-proxy: %v", err))
	}
}
