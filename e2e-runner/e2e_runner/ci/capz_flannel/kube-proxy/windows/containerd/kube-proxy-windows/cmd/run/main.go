package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"kube-proxy-windows/utils"
)

var (
	buildDir string = "/build"
)

func fixKubeconfig() error {
	fmt.Printf("fix kube-proxy kubeconfig.conf file\n")
	bytes, err := os.ReadFile(filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "var/lib/kube-proxy/kubeconfig.conf"))
	if err != nil {
		return err
	}
	newPath := filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "var")
	kubeconfig := strings.Replace(string(bytes), "/var", newPath, -1)
	if err := os.MkdirAll("/var/lib/kube-proxy", os.ModeDir); err != nil {
		return fmt.Errorf("error creating /var/lib/kube-proxy dir: %v", err)
	}
	if err := os.WriteFile("/var/lib/kube-proxy/kubeconfig.conf", []byte(kubeconfig), 0644); err != nil {
		return err
	}
	return nil
}

func main() {
	buildBinary := filepath.Join(buildDir, "kube-proxy.exe")
	if _, err := os.Stat(buildBinary); err == nil {
		fmt.Printf("kube-proxy build binary found (%s), using it", buildBinary)
		utils.CopyFile(
			buildBinary,
			filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "kube-proxy/kube-proxy.exe"),
		)
	}
	// this is a workaround since the go-client doesn't know about the path CONTAINER_SANDBOX_MOUNT_POINT from environment
	if err := fixKubeconfig(); err != nil {
		panic(fmt.Errorf("error fixing kube-proxy kubeconfig: %v", err))
	}
	cmd := exec.Command(
		filepath.Join(os.Getenv("CONTAINER_SANDBOX_MOUNT_POINT"), "kube-proxy/kube-proxy.exe"),
		fmt.Sprintf("--hostname-override=%s", os.Getenv("NODE_NAME")),
		fmt.Sprintf("--enable-dsr=%s", os.Getenv("ENABLE_WIN_DSR")),
		fmt.Sprintf("--config=%s", utils.KubeProxyConfFile),
		"--v=4",
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		panic(fmt.Errorf("error running kube-proxy: %v", err))
	}
}
