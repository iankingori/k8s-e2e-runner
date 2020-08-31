import glob
import shutil
import re
import os
import time

from distutils.util import strtobool

import configargparse
import yaml

import capz
import ci
import constants
import log
import utils

p = configargparse.get_argument_parser()

p.add("--container-runtime", default="docker",
      choices=["docker", "containerd"],
      help="Container runtime used by the Kubernetes agents.")
p.add("--flannel-mode", default=constants.FLANNEL_MODE_OVERLAY,
      choices=[constants.FLANNEL_MODE_OVERLAY,
               constants.FLANNEL_MODE_L2BRIDGE],
      help="Flannel mode used by the CI.")
p.add("--base-container-image-tag",
      default="ltsc2019", choices=["ltsc2019", "1909", "2004"],
      help="The base container image used for the kube-proxy / flannel CNI. "
      "This needs to be adjusted depending on the Windows minion Azure image.")
p.add("--kubernetes-version", default=constants.DEFAULT_KUBERNETES_VERSION,
      help="The Kubernetes version to deploy. If '--build=k8sbins' is "
      "specified, this parameter is overwriten by the version of the newly "
      "built k8s binaries")
p.add("--cri-tools-repo",
      default="https://github.com/kubernetes-sigs/cri-tools",
      help="The cri-tools repository. It is used to build the crictl tool.")
p.add("--cri-tools-branch",
      default="master", help="The cri-tools branch.")


class CapzFlannelCI(ci.CI):
    def __init__(self):
        super(CapzFlannelCI, self).__init__()

        self.logging = log.getLogger(__name__)
        self.kubectl = utils.get_kubectl_bin()
        self.patches = None

        self.kubernetes_version = self.opts.kubernetes_version
        self.ci_version = self.kubernetes_version
        self.ci_artifacts_dir = os.path.join(
            os.environ["HOME"], "ci_artifacts")
        os.makedirs(self.ci_artifacts_dir, exist_ok=True)

        self.deployer = capz.CAPZProvisioner(
            flannel_mode=self.opts.flannel_mode,
            container_runtime=self.opts.container_runtime,
            ci_artifacts_dir=self.ci_artifacts_dir,
            kubernetes_version=self.kubernetes_version)

    def build(self, bins_to_build):
        builder_mapping = {
            "k8sbins": self._build_k8s_artifacts,
            "containerdbins": self._build_containerd_binaries,
            "containerdshim": self._build_containerd_shim,
            "sdncnibins": self._build_sdn_cni_binaries,
        }

        def noop_func():
            pass

        for bins in bins_to_build:
            self.logging.info("Building %s binaries", bins)
            builder_mapping.get(bins, noop_func)()
            self.deployer.bins_built.append(bins)

    def up(self):
        start = time.time()

        self.deployer.up()
        self.deployer.wait_for_agents(check_nodes_ready=False, timeout=7200)
        if self.opts.flannel_mode == constants.FLANNEL_MODE_L2BRIDGE:
            self.deployer.enable_ip_forwarding()

        self.deployer.setup_ssh_config()
        self._setup_kubeconfig()

        if self.patches is not None:
            self._install_patches()

        if "k8sbins" in self.opts.build:
            self._upload_kube_proxy_windows_bin()

        self._add_flannel_cni()
        self._wait_for_ready_cni()
        if self.opts.flannel_mode == constants.FLANNEL_MODE_OVERLAY:
            self._allocate_win_source_vip()
        self._add_kube_proxy_windows()

        self._wait_for_ready_pods()
        self.deployer.wait_for_agents(check_nodes_ready=True)

        self.logging.info("The cluster provisioned in %.2f minutes",
                          (time.time() - start) / 60.0)
        self._validate_cluster()

    def down(self):
        self.deployer.down()

    def reclaim(self):
        self.deployer.reclaim()
        self._setup_kubeconfig()

    def collectWindowsLogs(self):
        if "KUBECONFIG" not in os.environ:
            self.logging.info("Skipping collection of Windows logs, because "
                              "KUBECONFIG is not set.")
            return

        local_script_path = os.path.join(
            os.getcwd(), "cluster-api/scripts/collect-logs.ps1")
        remote_script_path = os.path.join(
            "/tmp", os.path.basename(local_script_path))
        remote_cmd = remote_script_path
        remote_logs_archive = "/tmp/logs.zip"

        for node_address in self.deployer.windows_private_addresses:
            try:
                self._collect_logs(
                    node_address, local_script_path, remote_script_path,
                    remote_cmd, remote_logs_archive)
            except Exception as ex:
                self.logging.warning(
                    "Cannot collect logs from node %s. Exception details: "
                    "%s. Skipping", node_address, ex)

    def collectLinuxLogs(self):
        if "KUBECONFIG" not in os.environ:
            self.logging.info("Skipping collection of Linux logs, because "
                              "KUBECONFIG is not set.")
            return

        local_script_path = os.path.join(
            os.getcwd(), "cluster-api/scripts/collect-logs.sh")
        remote_script_path = os.path.join(
            "/tmp", os.path.basename(local_script_path))
        remote_cmd = "sudo bash %s" % remote_script_path
        remote_logs_archive = "/tmp/logs.tar.gz"

        for node_address in self.deployer.linux_private_addresses:
            try:
                self._collect_logs(
                    node_address, local_script_path, remote_script_path,
                    remote_cmd, remote_logs_archive)
            except Exception as ex:
                self.logging.warning(
                    "Cannot collect logs from node %s. Exception details: "
                    "%s. Skipping", node_address, ex)

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
            utils.retry_on_error()(self.deployer.run_cmd_on_k8s_node)(
                cmd, node_address)

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

    def _prepare_test_env(self):
        self.logging.info("Preparing test env")

        utils.clone_git_repo(
            self.opts.k8s_repo, self.opts.k8s_branch, utils.get_k8s_folder())

        os.environ["KUBE_MASTER"] = "local"
        os.environ["KUBE_MASTER_IP"] = self.deployer.master_public_address
        os.environ["KUBE_MASTER_URL"] = "https://%s:%s" % (
            self.deployer.master_public_address,
            self.deployer.master_public_port)

        self._setup_kubeconfig()
        if self.opts.container_runtime == "docker":
            self._prepull_images()

    def _prepull_images(self, timeout=3600):
        prepull_yaml_path = "/tmp/prepull-windows-images.yaml"
        utils.download_file(self.opts.prepull_yaml, prepull_yaml_path)

        self.logging.info("Starting Windows images pre-pull")
        utils.retry_on_error()(utils.run_shell_cmd)(
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
                utils.run_shell_cmd)(cmd, sensitive=True)
            prepull_daemonset = yaml.safe_load(output.decode("ascii"))

            if (prepull_daemonset["status"]["numberReady"] ==
                    prepull_daemonset["status"]["desiredNumberScheduled"]):
                break

            time.sleep(sleep_time)

        self.logging.info("Windows images pre-pulled in %.2f minutes",
                          (time.time() - start) / 60.0)

        self.logging.info("Cleaning up")
        utils.run_shell_cmd(
            [self.kubectl, "delete", "--wait", "-f", prepull_yaml_path])

    def _validate_cluster(self):
        self.logging.info("Validating cluster")
        self._validate_k8s_api_versions()
        self._validate_k8s_api_container_images()

    def _validate_k8s_api_versions(self):
        self.logging.info("Validating K8s API versions")

        output, _ = utils.retry_on_error()(
            utils.run_shell_cmd)([self.kubectl, "get", "nodes", "-o", "yaml"])
        nodes = yaml.safe_load(output.decode("ascii"))
        for node in nodes["items"]:
            node_name = node["metadata"]["name"]
            node_info = node["status"]["nodeInfo"]

            if node_info["kubeletVersion"] != self.ci_version:
                raise Exception(
                    "Wrong kubelet version on node %s. "
                    "Expected %s, but found %s" %
                    (node_name, self.ci_version, node_info["kubeletVersion"]))

            if node_info["kubeProxyVersion"] != self.ci_version:
                raise Exception(
                    "Wrong kube-proxy version on node %s. "
                    "Expected %s, but found %s" %
                    (node_name, self.ci_version, node_info["kubeletVersion"]))

    def _validate_k8s_api_container_images(self):
        self.logging.info("Validating K8s API container images")

        output, _ = utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "get", "nodes", "-o", "yaml", "-l",
            "kubernetes.io/os=linux"
        ])
        nodes = yaml.safe_load(output.decode("ascii"))

        images_tag = self.ci_version.replace("+", "_").strip("v")
        name_regex = re.compile(r"^(k8s.gcr.io/kube-.*):v(.*)$")
        for node in nodes["items"]:
            non_ci_images_names = []
            for image in node["status"]["images"]:
                non_ci_images_names += [
                    name for name in image["names"]
                    if (name_regex.match(name)
                        and name_regex.match(name).group(2) != images_tag)]

                if len(non_ci_images_names) > 0:
                    self.logging.error(
                        "Found the following non-CI images %s on the "
                        "node %s.", non_ci_images_names,
                        node["metadata"]["name"])
                    raise Exception("Found non-CI container images on "
                                    "node %s" % node["metadata"]["name"])

    def _wait_for_ready_pods(self):
        self.logging.info("Waiting for all the pods to be ready")
        utils.run_shell_cmd([
            self.kubectl, "wait", "--for=condition=Ready", "--timeout", "30m",
            "pods", "--all", "--all-namespaces"
        ])

    def _upload_kube_proxy_windows_bin(self):
        self.logging.info("Uploading the kube-proxy.exe to the Windows agents")

        win_node_addresses = self.deployer.windows_private_addresses
        kube_proxy_bin = "%s/%s/bin/windows/amd64/kube-proxy.exe" % (
            self.ci_artifacts_dir, self.ci_version)

        self._run_remote_cmd("mkdir -force /build", win_node_addresses)
        self._upload_to(
            kube_proxy_bin, "/build/kube-proxy.exe", win_node_addresses)

    def _allocate_win_source_vip(self):
        self.logging.info("Allocating source VIP for the Windows agents")

        local_script_path = os.path.join(
            os.getcwd(), "cluster-api/scripts/allocate-source-vip.ps1")
        remote_script_path = "/tmp/allocate-source-vip.ps1"
        win_node_addresses = self.deployer.windows_private_addresses

        self._upload_to(
            local_script_path, remote_script_path, win_node_addresses)
        self._run_remote_cmd(remote_script_path, win_node_addresses)

    def _wait_for_ready_cni(self, timeout=900):
        self.logging.info(
            "Waiting up to %.2f minutes for ready CNI on the Windows agents",
            timeout / 60.0)

        win_node_addresses = self.deployer.windows_private_addresses
        local_script_path = os.path.join(
            os.getcwd(), "cluster-api/scripts/confirm-ready-cni.ps1")
        remote_script_path = "/tmp/confirm-ready-cni.ps1"

        self._upload_to(
            local_script_path, remote_script_path, win_node_addresses)

        sleep_time = 10
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                err_msg = "The CNI was not ready within %s minutes." % (
                    timeout / 60.0)
                self.logging.error(err_msg)
                raise Exception(err_msg)

            all_ready = True
            for node_address in win_node_addresses:
                cmd = ["timeout", "1m", "ssh", node_address,
                       remote_script_path]
                try:
                    stdout, _ = utils.run_shell_cmd(cmd, sensitive=True)
                except Exception:
                    all_ready = False
                    break

                cni_ready = strtobool(stdout.decode('ascii').strip())
                if not cni_ready:
                    all_ready = False
                    break

            if all_ready:
                self.logging.info(
                    "The CNI is ready on all the Windows agents")
                break

            time.sleep(sleep_time)

    def _add_kube_proxy_windows(self):
        template_file = os.path.join(
            os.getcwd(), "cluster-api/kube-proxy/kube-proxy-windows.yaml.j2")
        server_core_tag = "windowsservercore-%s" % (
            self.opts.base_container_image_tag)
        context = {
            "kubernetes_version": self.kubernetes_version,
            "server_core_tag": server_core_tag,
            "enable_win_dsr": str(self.opts.install_dsr).lower(),
            "flannel_mode": self.opts.flannel_mode
        }
        output_file = "/tmp/kube-proxy-windows.yaml"
        utils.render_template(template_file, output_file, context)

        cmd = [self.kubectl, "apply", "-f", output_file]
        utils.retry_on_error()(utils.run_shell_cmd)(cmd)

    def _set_vxlan_devices_mtu(self):
        self.logging.info(
            "Set the proper MTU for the k8s master vxlan devices")
        ssh_key_path = (os.environ.get("SSH_KEY")
                        or os.path.join(os.environ.get("HOME"), ".ssh/id_rsa"))
        utils.retry_on_error()(utils.run_shell_cmd)([
            "ssh", "-o", "StrictHostKeyChecking=no", "-o",
            "UserKnownHostsFile=/dev/null", "-i", ssh_key_path,
            "capi@%s" % self.deployer.master_public_address,
            "'sudo bash -s' < %s" % os.path.join(
                os.getcwd(),
                "cluster-api/scripts/set-vxlan-devices-mtu.sh")
        ])

    def _add_flannel_cni(self):
        template_file = os.path.join(
            os.getcwd(), "cluster-api/flannel/kube-flannel.yaml.j2")
        context = {
            "cluster_network_subnet": self.deployer.cluster_network_subnet,
            "flannel_mode": self.opts.flannel_mode
        }
        kube_flannel = "/tmp/kube-flannel.yaml"
        utils.render_template(template_file, kube_flannel, context)

        server_core_tag = "windowsservercore-%s" % (
            self.opts.base_container_image_tag)
        mode = "overlay"
        if self.opts.flannel_mode == constants.FLANNEL_MODE_L2BRIDGE:
            mode = "l2bridge"
        context = {
            "server_core_tag": server_core_tag,
            "container_runtime": self.opts.container_runtime,
            "mode": mode
        }
        kube_flannel_windows = "/tmp/kube-flannel-windows.yaml"
        searchpath = os.path.join(os.getcwd(), "cluster-api/flannel")
        utils.render_template("kube-flannel-windows.yaml.j2",
                              kube_flannel_windows, context, searchpath)

        cmd = [self.kubectl, "apply", "-f", kube_flannel]
        utils.retry_on_error()(utils.run_shell_cmd)(cmd)

        cmd = [self.kubectl, "apply", "-f", kube_flannel_windows]
        utils.retry_on_error()(utils.run_shell_cmd)(cmd)

        if self.opts.flannel_mode == constants.FLANNEL_MODE_OVERLAY:
            self._set_vxlan_devices_mtu()

    def _setup_kubeconfig(self):
        os.environ["KUBECONFIG"] = self.deployer.capz_kubeconfig_path

    def _build_k8s_artifacts(self):
        k8s_path = utils.get_k8s_folder()
        utils.clone_git_repo(
            self.opts.k8s_repo, self.opts.k8s_branch, k8s_path)

        self.logging.info("Building K8s Linux binaries")
        cmd = [
            'make', 'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm"',
            'KUBE_BUILD_PLATFORMS="linux/amd64"'
        ]
        utils.run_shell_cmd(cmd, k8s_path)

        self.logging.info("Building K8s Windows binaries")
        cmd = [
            'make',
            'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm cmd/kube-proxy"',
            'KUBE_BUILD_PLATFORMS="windows/amd64"'
        ]
        utils.run_shell_cmd(cmd, k8s_path)

        self.logging.info("Building K8s Linux DaemonSet container images")
        cmd = ['make', 'quick-release-images']
        env = {"KUBE_FASTBUILD": "true",
               "KUBE_BUILD_CONFORMANCE": "n"}
        utils.retry_on_error()(utils.run_shell_cmd)(cmd, k8s_path, env)

        kubeadm_bin = os.path.join(constants.KUBERNETES_LINUX_BINS_LOCATION,
                                   'kubeadm')
        out, _ = utils.run_shell_cmd(
            [kubeadm_bin, "version", "-o=short"], k8s_path)
        self.ci_version = out.decode().strip()
        self.deployer.ci_version = self.ci_version

        ci_artifacts_linux_bin_dir = "%s/%s/bin/linux/amd64" % (
            self.ci_artifacts_dir, self.ci_version)
        ci_artifacts_windows_bin_dir = "%s/%s/bin/windows/amd64" % (
            self.ci_artifacts_dir, self.ci_version)
        ci_artifacts_images_dir = "%s/%s/images" % (
            self.ci_artifacts_dir, self.ci_version)

        os.makedirs(ci_artifacts_linux_bin_dir, exist_ok=True)
        os.makedirs(ci_artifacts_windows_bin_dir, exist_ok=True)
        os.makedirs(ci_artifacts_images_dir, exist_ok=True)

        for bin_name in ["kubectl", "kubelet", "kubeadm"]:
            linux_bin_path = "%s/%s/%s" % (
                k8s_path, constants.KUBERNETES_LINUX_BINS_LOCATION, bin_name)
            shutil.copy(linux_bin_path, ci_artifacts_linux_bin_dir)

        for bin_name in ["kubectl", "kubelet", "kubeadm", "kube-proxy"]:
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

    def _build_containerd_binaries(self):
        containerd_path = utils.get_containerd_folder()
        utils.clone_git_repo(self.opts.containerd_repo,
                             self.opts.containerd_branch, containerd_path)

        ctr_path = utils.get_ctr_folder()
        utils.clone_git_repo(self.opts.ctr_repo,
                             self.opts.ctr_branch, ctr_path)

        gopath = utils.get_go_path()
        cri_tools_path = os.path.join(
            gopath, "src", "github.com", "kubernetes-sigs", "cri-tools")
        utils.clone_git_repo(self.opts.cri_tools_repo,
                             self.opts.cri_tools_branch, cri_tools_path)

        self.logging.info("Building containerd with cri plugin")
        utils.run_shell_cmd(["GOOS=windows", "make"], containerd_path)

        self.logging.info("Building ctr")
        utils.run_shell_cmd(["GOOS=windows", "make", "bin/ctr.exe"], ctr_path)

        self.logging.info("Building crictl")
        utils.run_shell_cmd(["GOOS=windows", "make", "crictl"], cri_tools_path)

        self.logging.info("Copying binaries to local artifacts directory")
        ci_artifacts_containerd_bin_dir = os.path.join(
            self.ci_artifacts_dir, "containerd/bin")
        os.makedirs(ci_artifacts_containerd_bin_dir, exist_ok=True)

        containerd_bins_location = os.path.join(
            containerd_path, constants.CONTAINERD_BINS_LOCATION)
        for path in glob.glob("%s/*" % containerd_bins_location):
            shutil.copy(path, ci_artifacts_containerd_bin_dir)

        ctr_bin = os.path.join(ctr_path, constants.CONTAINERD_CTR_LOCATION)
        shutil.copy(ctr_bin, ci_artifacts_containerd_bin_dir)

        crictl_bin = os.path.join(cri_tools_path, "_output/crictl.exe")
        shutil.copy(crictl_bin, ci_artifacts_containerd_bin_dir)

    def _build_containerd_shim(self):
        fromVendor = False
        if self.opts.containerd_shim_repo is None:
            fromVendor = True

        containerd_shim_path = utils.get_containerd_shim_folder(fromVendor)

        if fromVendor:
            utils.run_shell_cmd(["go", "get", "github.com/LK4D4/vndr"])

            cmd = ["vndr", "-whitelist", "hcsshim",
                   "github.com/Microsoft/hcsshim"]
            vendoring_path = utils.get_containerd_folder()
            utils.run_shell_cmd(cmd, vendoring_path)
        else:
            utils.clone_git_repo(self.opts.containerd_shim_repo,
                                 self.opts.containerd_shim_branch,
                                 containerd_shim_path)

        self.logging.info("Building containerd shim")
        cmd = [
            "GOOS=windows", "go", "build", "-o", constants.CONTAINERD_SHIM_BIN,
            constants.CONTAINERD_SHIM_DIR
        ]
        utils.run_shell_cmd(cmd, containerd_shim_path)

        self.logging.info("Copying binaries to local artifacts directory")
        ci_artifacts_containerd_bin_dir = os.path.join(
            self.ci_artifacts_dir, "containerd/bin")
        os.makedirs(ci_artifacts_containerd_bin_dir, exist_ok=True)

        containerd_shim_bin = os.path.join(
            containerd_shim_path, constants.CONTAINERD_SHIM_BIN)
        shutil.copy(containerd_shim_bin, ci_artifacts_containerd_bin_dir)

    def _build_sdn_cni_binaries(self):
        sdn_cni_dir = utils.get_sdn_folder()
        utils.clone_git_repo(
            self.opts.sdn_repo, self.opts.sdn_branch, sdn_cni_dir)

        self.logging.info("Building the SDN CNI binaries")
        utils.run_shell_cmd(["GOOS=windows", "make", "all"], sdn_cni_dir)

        self.logging.info("Copying binaries to local artifacts directory")
        ci_artifacts_cni_dir = os.path.join(self.ci_artifacts_dir, "cni")
        os.makedirs(ci_artifacts_cni_dir, exist_ok=True)

        sdn_binaries_names = ["nat.exe", "sdnbridge.exe", "sdnoverlay.exe"]
        for sdn_bin_name in sdn_binaries_names:
            sdn_bin = os.path.join(sdn_cni_dir, "out", sdn_bin_name)
            shutil.copy(sdn_bin, ci_artifacts_cni_dir)

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

        node_name, _ = self.deployer.run_cmd_on_k8s_node(
            "hostname", node_address)

        local_logs_archive = os.path.join(
            self.opts.log_path,
            "%s-%s" % (node_name, os.path.basename(remote_logs_archive)))
        self.deployer.download_from_k8s_node(
            remote_logs_archive, local_logs_archive, node_address)

        self.logging.info("Finished collecting logs from node %s",
                          node_name)
