import shutil
import os
import time

import configargparse
import yaml

import capz
import ci
import constants
import log
import utils

p = configargparse.get_argument_parser()

p.add("--base-container-image-tag",
      default="1809", choices=["1809", "2004"],
      help="The base container image used for the kube-proxy / flannel CNI. "
      "This needs to be adjusted depending on the Windows minion Azure image.")


class CapzFlannelCI(ci.CI):
    def __init__(self):
        super(CapzFlannelCI, self).__init__()

        self.logging = log.getLogger(__name__)
        self.kubectl = utils.get_kubectl_bin()
        self.patches = None

        # set after k8sbins build
        self.ci_version = None

        self.deployer = capz.CAPZProvisioner()

    def build(self, binsToBuild):
        builder_mapping = {"k8sbins": self._build_k8s_artifacts}

        def noop_func():
            pass

        for bins in binsToBuild:
            self.logging.info("Building %s binaries", bins)
            builder_mapping.get(bins, noop_func)()

    def up(self):
        start = time.time()

        self.deployer.up()
        self.deployer.wait_for_agents(check_nodes_ready=False)

        if self.patches is not None:
            self._install_patches()

        self._setup_kubeconfig()
        self._add_flannel_cni()
        self._add_kube_proxy_windows_daemonset()

        self.deployer.wait_for_agents(check_nodes_ready=True)
        self._wait_for_ready_pods()

        self.logging.info("The cluster provisioned in %.2f minutes",
                          (time.time() - start) / 60.0)

        self._validate_cluster()

    def down(self):
        self.deployer.down()

    def reclaim(self):
        self.deployer.reclaim()
        self._setup_kubeconfig()

    def collectWindowsLogs(self):
        local_script_path = os.path.join(
            os.getcwd(), "cluster-api/scripts/collect-logs.ps1")
        remote_script_path = os.path.join(
            "/tmp", os.path.basename(local_script_path))
        remote_cmd = remote_script_path
        remote_logs_archive = "/tmp/logs.zip"

        for node_address in self.deployer.windows_private_addresses:
            self._collect_logs(
                node_address, local_script_path, remote_script_path,
                remote_cmd, remote_logs_archive)

    def collectLinuxLogs(self):
        local_script_path = os.path.join(
            os.getcwd(), "cluster-api/scripts/collect-logs.sh")
        remote_script_path = os.path.join(
            "/tmp", os.path.basename(local_script_path))
        remote_cmd = "sudo bash %s" % remote_script_path
        remote_logs_archive = "/tmp/logs.tar.gz"

        for node_address in self.deployer.linux_private_addresses:
            self._collect_logs(
                node_address, local_script_path, remote_script_path,
                remote_cmd, remote_logs_archive)

    def set_patches(self, patches=None):
        self.patches = patches

    def _install_patches(self):
        self.logging.info("Installing patches")

        local_script_path = os.path.join(os.getcwd(), "installPatches.ps1")
        node_addresses = self.deployer.windows_private_addresses

        self._upload_to(local_script_path,
                        "/tmp/installPatches.ps1",
                        node_addresses)
        self._run_remote_cmd("/tmp/installPatches.ps1 %s" % self.patches,
                             node_addresses)
        self._wait_for_connection(node_addresses)

    def _upload_to(self, local_path, remote_path, node_addresses):
        for node_address in node_addresses:
            self.deployer.upload_to_k8s_node(
                local_path, remote_path, node_address)

    def _run_remote_cmd(self, cmd, node_addresses):
        for node_address in node_addresses:
            self.deployer.run_cmd_on_k8s_node(cmd, node_address)

    def _wait_for_connection(self, node_addresses, timeout=600):
        self.logging.info(
            "Waiting up to %.2f minutes for nodes %s connectivity",
            timeout / 60.0, node_addresses)

        sleep_time = 5
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                err_msg = "Nodes were not up within %s minutes." % (
                    timeout / 60)
                self.logging.error(err_msg)
                raise Exception(err_msg)

            all_ready = True
            for node_address in node_addresses:
                if not self.deployer.check_k8s_node_connection(node_address):
                    self.logging.warning("Node %s is not up yet", node_address)
                    all_ready = False

            if all_ready:
                self.logging.info("All the nodes are up")
                break

            time.sleep(sleep_time)

    def _prepareTestEnv(self):
        self.logging.info("Preparing test env")

        os.environ["KUBE_MASTER"] = "local"
        os.environ["KUBE_MASTER_IP"] = self.deployer.master_public_address
        os.environ["KUBE_MASTER_URL"] = "https://%s:%s" % (
            self.deployer.master_public_address,
            self.deployer.master_public_port)

        self._setup_kubeconfig()
        self._prepull_images()

    def _prepull_images(self, timeout=3600):
        prepull_yaml_path = "/tmp/prepull-windows-images.yaml"
        utils.download_file(self.opts.prepull_yaml, prepull_yaml_path)

        self.logging.info("Starting Windows images pre-pull")
        utils.retry_on_error()(self._run_cmd)(
            [self.kubectl, "apply", "-f", prepull_yaml_path])

        self.logging.info(
            "Waiting up to %.2f minutes to pre-pull Windows container images",
            timeout / 60.0)

        sleep_time = 5
        start = time.time()
        cmd = [self.kubectl, "get", "-o", "yaml", "-f", prepull_yaml_path]
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise Exception("Couldn't pre-pull Windows images within "
                                "%.2f minutes." % (timeout / 60.0))

            output, _ = utils.retry_on_error()(
                self._run_cmd)(cmd, sensitive=True)
            prepull_daemonset = yaml.safe_load(output.decode("ascii"))

            if (prepull_daemonset["status"]["numberReady"] ==
                    prepull_daemonset["status"]["desiredNumberScheduled"]):
                break

            time.sleep(sleep_time)

        self.logging.info("Windows images pre-pulled in %.2f minutes",
                          (time.time() - start) / 60.0)

        self.logging.info("Cleaning up")
        self._run_cmd(
            [self.kubectl, "delete", "--wait", "-f", prepull_yaml_path])

    def _validate_cluster(self):
        self.logging.info("Validating cluster")
        self._validate_k8s_api_versions()
        self._validate_k8s_api_container_images()

    def _validate_k8s_api_versions(self):
        if not self.ci_version:
            raise Exception("The variable ci_version is not set")

        self.logging.info("Validating K8s API versions")

        output, _ = utils.retry_on_error()(
            self._run_cmd)([self.kubectl, "get", "nodes", "-o", "yaml"])
        nodes = yaml.safe_load(output.decode("ascii"))
        for node in nodes["items"]:
            node_name = node["metadata"]["name"]
            node_info = node["status"]["nodeInfo"]
            node_os = node["metadata"]["labels"]["kubernetes.io/os"]

            if node_info["kubeletVersion"] != self.ci_version:
                raise Exception(
                    "Wrong kubelet version on node %s. "
                    "Expected %s, but found %s" %
                    (node_name, self.ci_version, node_info["kubeletVersion"]))

            # Skip kube-proxy version validation for Windows nodes, if
            # DSR patch is applied.
            if self.opts.install_dsr and node_os == "windows":
                self.logging.warning(
                    "Skipping kube-proxy version check for node %s. The "
                    "node version is %s.", node_name,
                    node_info["kubeProxyVersion"])
                continue

            if node_info["kubeProxyVersion"] != self.ci_version:
                raise Exception(
                    "Wrong kube-proxy version on node %s. "
                    "Expected %s, but found %s" %
                    (node_name, self.ci_version, node_info["kubeletVersion"]))

    def _validate_k8s_api_container_images(self):
        if not self.ci_version:
            raise Exception("The variable ci_version is not set")

        self.logging.info("Validating K8s API container images")

        output, _ = utils.retry_on_error()(self._run_cmd)([
            self.kubectl, "get", "nodes", "-o", "yaml", "-l",
            "kubernetes.io/os=linux"
        ])
        nodes = yaml.safe_load(output.decode("ascii"))

        images_tag = self.ci_version.replace("+", "_")
        for node in nodes["items"]:
            non_ci_images_names = []
            for image in node["status"]["images"]:
                non_ci_images_names += [
                    name for name in image["names"]
                    if (name.startswith("k8s.gcr.io/kube-")
                        and not name.endswith(images_tag))
                ]

                if len(non_ci_images_names) > 0:
                    self.logging.error(
                        "Found the following non-CI images %s on the "
                        "node %s.", non_ci_images_names,
                        node["metadata"]["name"])
                    raise Exception("Found non-CI container images on "
                                    "node %s" % node["metadata"]["name"])

    def _wait_for_ready_pods(self):
        self.logging.info("Waiting for all the pods to be ready")
        self._run_cmd([
            self.kubectl, "wait", "--for=condition=Ready", "--timeout", "20m",
            "pods", "--all", "--all-namespaces"
        ])

    def _add_kube_proxy_windows_daemonset(self):
        template_file = os.path.join(
            os.getcwd(), "cluster-api/kube-proxy/daemonset-windows.yaml.j2")
        context = {
            "ci_image_tag": self.ci_version.replace("+", "_"),
            "enable_win_dsr": str(self.opts.install_dsr).lower()
        }
        output_file = "/tmp/kube-proxy-daemonset-windows.yaml"
        utils.render_template(template_file, output_file, context)

        cmd = [self.kubectl, "apply", "-f", output_file]
        utils.retry_on_error()(self._run_cmd)(cmd)

    def _add_flannel_cni(self):
        template_file = os.path.join(
            os.getcwd(), "cluster-api/flannel/daemonset-linux.yaml.j2")
        context = {
            "cluster_network_subnet": self.deployer.cluster_network_subnet
        }
        flannel_daemonset_linux = "/tmp/flannel-daemonset-linux.yaml"
        utils.render_template(template_file, flannel_daemonset_linux, context)

        flannel_addons = os.path.join(os.getcwd(),
                                      "cluster-api/flannel/addons.yaml")

        template_file = os.path.join(
            os.getcwd(), "cluster-api/flannel/daemonset-windows.yaml.j2")
        server_core_tag = "windowsservercore-%s" % (
            self.opts.base_container_image_tag)
        context = {"server_core_tag": server_core_tag}
        flannel_daemonset_windows = "/tmp/flannel-daemonset-windows.yaml"
        utils.render_template(
            template_file, flannel_daemonset_windows, context)

        cmd = [self.kubectl, "apply", "-f", flannel_addons]
        utils.retry_on_error()(self._run_cmd)(cmd)

        cmd = [self.kubectl, "apply", "-f", flannel_daemonset_linux]
        utils.retry_on_error()(self._run_cmd)(cmd)

        cmd = [self.kubectl, "apply", "-f", flannel_daemonset_windows]
        utils.retry_on_error()(self._run_cmd)(cmd)

        # TODO: run the MTU change only when vxlan overlay is used
        self.logging.info(
            "Set the proper MTU for the k8s master vxlan devices")
        ssh_key_path = (os.environ.get("SSH_KEY")
                        or os.path.join(os.environ.get("HOME"), ".ssh/id_rsa"))
        utils.retry_on_error()(self._run_cmd)([
            "ssh", "-o", "StrictHostKeyChecking=no", "-o",
            "UserKnownHostsFile=/dev/null", "-i", ssh_key_path,
            "capi@%s" % self.deployer.master_public_address,
            "'sudo bash -s' < %s" % os.path.join(
                os.getcwd(),
                "cluster-api/scripts/set-vxlan-devices-mtu.sh")
        ])

    def _setup_kubeconfig(self):
        os.environ["KUBECONFIG"] = self.deployer.capz_kubeconfig_path

    def _build_kube_proxy_win_image(self,
                                    output_file="/tmp/kube-proxy-windows.tar"):
        self.logging.info("Building kube-proxy Windows DaemonSet image")

        # Setup docker buildx
        env = {"DOCKER_CLI_EXPERIMENTAL": "enabled"}
        cmd = [
            "docker buildx ls | grep -q docker-buildx", "||",
            "docker buildx create --name docker-buildx"
        ]
        self._run_cmd(cmd, env=env)
        self._run_cmd(["docker buildx use docker-buildx"], env=env)

        # Cross-build kube-proxy Windows image
        ci_image_tag = self.ci_version.replace("+", "_")
        dockerfile_path = os.path.join(
            os.getcwd(),
            "cluster-api/kube-proxy/daemonset-windows-buildx.Dockerfile")
        base_image_tag = "v1.18.5-windowsservercore-%s" % (
            self.opts.base_container_image_tag)
        cmd = [
            "docker", "buildx", "build", "-f", dockerfile_path, "-t",
            "e2eteam/kube-proxy-windows:%s" % ci_image_tag, "--build-arg",
            "baseImage=e2eteam/kube-proxy-windows:%s" % base_image_tag,
            "--platform=windows/amd64",
            "--output=type=docker,dest=%s" % output_file,
            "%s/%s" % (utils.get_k8s_folder(),
                       constants.KUBERNETES_WINDOWS_BINS_LOCATION)
        ]
        utils.retry_on_error()(self._run_cmd)(cmd, env=env)

    def _build_k8s_artifacts(self):
        k8s_path = utils.get_k8s_folder()
        utils.clone_repo(self.opts.k8s_repo, self.opts.k8s_branch, k8s_path)

        self.logging.info("Building K8s Linux binaries")
        cmd = [
            'make', 'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm"',
            'KUBE_BUILD_PLATFORMS="linux/amd64"'
        ]
        self._run_cmd(cmd, k8s_path)

        self.logging.info("Building K8s Windows binaries")
        cmd = [
            'make',
            'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm cmd/kube-proxy"',
            'KUBE_BUILD_PLATFORMS="windows/amd64"'
        ]
        self._run_cmd(cmd, k8s_path)

        self.logging.info("Building K8s Linux DaemonSet Docker images")
        cmd = ['make', 'quick-release-images']
        utils.retry_on_error()(self._run_cmd)(cmd, k8s_path)

        kubeadm_bin = os.path.join(constants.KUBERNETES_LINUX_BINS_LOCATION,
                                   'kubeadm')
        out, _ = self._run_cmd([kubeadm_bin, "version", "-o=short"], k8s_path)
        self.ci_version = out.decode().strip()
        self.deployer.ci_version = self.ci_version

        ci_artifacts_dir = "%s/ci_artifacts" % os.environ["HOME"]
        ci_artifacts_linux_bin_dir = "%s/%s/bin/linux/amd64" % (
            ci_artifacts_dir, self.ci_version)
        ci_artifacts_windows_bin_dir = "%s/%s/bin/windows/amd64" % (
            ci_artifacts_dir, self.ci_version)
        ci_artifacts_images_dir = "%s/%s/images" % (
            ci_artifacts_dir, self.ci_version)

        if self.opts.install_dsr:
            ret = utils.retry_on_error()(utils.download_file)(
                "http://10.0.173.212/kube-proxy.exe",
                "%s/%s/kube-proxy.exe" % (
                    k8s_path, constants.KUBERNETES_WINDOWS_BINS_LOCATION))
            if ret != 0:
                raise Exception("Failed to download kube-proxy.exe with "
                                "DSR patch")

        os.makedirs(ci_artifacts_linux_bin_dir, exist_ok=True)
        os.makedirs(ci_artifacts_windows_bin_dir, exist_ok=True)
        os.makedirs(ci_artifacts_images_dir, exist_ok=True)

        for bin_name in ["kubectl", "kubelet", "kubeadm"]:
            linux_bin_path = "%s/%s/%s" % (
                k8s_path, constants.KUBERNETES_LINUX_BINS_LOCATION, bin_name)
            shutil.copy(linux_bin_path, ci_artifacts_linux_bin_dir)

            win_bin_path = "%s/%s/%s.exe" % (
                k8s_path, constants.KUBERNETES_WINDOWS_BINS_LOCATION, bin_name)
            shutil.copy(win_bin_path, ci_artifacts_windows_bin_dir)

        images_names = [
            "kube-apiserver.tar", "kube-controller-manager.tar",
            "kube-proxy.tar", "kube-scheduler.tar"
        ]
        for image_name in images_names:
            image_path = "%s/%s/%s" % (
                k8s_path, constants.KUBERNETES_IMAGES_LOCATION,
                image_name)
            shutil.copy(image_path, ci_artifacts_images_dir)

        kube_proxy_windows_image_file = "%s/%s" % (
            ci_artifacts_images_dir, "kube-proxy-windows.tar")
        self._build_kube_proxy_win_image(kube_proxy_windows_image_file)

        self.deployer.ci_artifacts_dir = ci_artifacts_dir

    def _run_cmd(self, cmd, cwd=None, env=None, sensitive=False):
        out, err, ret = utils.run_cmd(cmd,
                                      timeout=(3 * 3600),
                                      stdout=True,
                                      stderr=True,
                                      cwd=cwd,
                                      env=env,
                                      shell=True,
                                      sensitive=sensitive)
        if ret != 0:
            raise Exception("Failed to execute: %s. Error: %s" %
                            (' '.join(cmd), err))
        return (out, err)

    def _collect_logs(self, node_address, local_script_path,
                      remote_script_path, remote_cmd, remote_logs_archive):
        self.logging.info("Collecting logs from node %s", node_address)

        if not self.deployer.check_k8s_node_connection(node_address):
            self.logging.warning(
                "No SSH connectivity to node %s. Skipping logs collection",
                node_address)
            return

        self.deployer.upload_to_k8s_node(
            local_script_path, remote_script_path, node_address)

        self.deployer.run_cmd_on_k8s_node(remote_cmd, node_address)

        output, _ = self.deployer.run_cmd_on_k8s_node("hostname", node_address)
        node_name = output.decode('ascii').strip()

        local_logs_archive = os.path.join(
            self.opts.log_path,
            "%s-%s" % (node_name, os.path.basename(remote_logs_archive)))
        self.deployer.download_from_k8s_node(
            remote_logs_archive, local_logs_archive, node_address)

        self.logging.info("Finished collecting logs from node %s",
                          node_name)
