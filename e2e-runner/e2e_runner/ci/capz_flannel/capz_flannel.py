import re
import os
import subprocess
import time
import sh
import yaml

from datetime import datetime
from distutils.util import strtobool
from tenacity import (
    Retrying,
    stop_after_delay,
    wait_exponential,
    retry_if_exception_type,
)
from e2e_runner import (
    base,
    constants,
    logger,
    utils
)
from e2e_runner.deployer.capz import capz


class CapzFlannelCI(base.CI):

    def __init__(self, opts):
        super(CapzFlannelCI, self).__init__(opts)

        self.capz_flannel_dir = os.path.dirname(__file__)

        self.logging = logger.get_logger(__name__)
        self.kubectl = utils.get_kubectl_bin()
        self.patches = []

        self.kubernetes_version = self.opts.kubernetes_version
        self.ci_version = self.kubernetes_version
        self.ci_artifacts_dir = os.path.join(
            os.environ["HOME"], "ci_artifacts")

        self.deployer = capz.CAPZProvisioner(
            opts,
            flannel_mode=self.opts.flannel_mode,
            container_runtime=self.opts.container_runtime,
            kubernetes_version=self.kubernetes_version,
            resource_group_tags=self.resource_group_tags)

    @property
    def resource_group_tags(self):
        tags = {
            'creationTimestamp': datetime.utcnow().isoformat(),
            'ciName': 'k8s-sig-win-networking-prow-flannel-e2e',
        }
        build_id = os.environ.get('BUILD_ID')
        if build_id:
            tags['buildID'] = build_id
        job_name = os.environ.get('JOB_NAME')
        if job_name:
            tags['jobName'] = job_name
        return tags

    def setup_infra(self):
        return self.deployer.setup_infra()

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
        if self.opts.flannel_mode == constants.FLANNEL_MODE_L2BRIDGE:
            self.deployer.connect_agents_to_controlplane_subnet()
        self.deployer.setup_ssh_config()
        self._setup_kubeconfig()
        self._install_patches()
        if "k8sbins" in self.deployer.bins_built:
            self._upload_kube_proxy_windows_bin()
        self._add_flannel_cni()
        self._wait_for_ready_cni()
        if self.opts.flannel_mode == constants.FLANNEL_MODE_OVERLAY:
            self._allocate_win_source_vip()
        self._add_kube_proxy_windows()
        self._wait_for_ready_pods()
        self.logging.info("The cluster provisioned in %.2f minutes",
                          (time.time() - start) / 60.0)
        self._validate_cluster()
        # The below deployer properties are cached, after their first call.
        # However, they use the management CAPI cluster (from the bootstrap
        # VM) to find the appropriate values when first called. Therefore,
        # make sure we cache them before cleaning up the bootstrap VM.
        self.deployer.master_public_address
        self.deployer.master_public_port
        self.deployer.linux_private_addresses
        self.deployer.windows_private_addresses
        # Once the CAPZ cluster is deployed, we don't need the
        # bootstrap VM anymore.
        self.deployer.collect_bootstrap_vm_logs()
        self.deployer.cleanup_bootstrap_vm()

    def down(self):
        self.deployer.down(wait=False)

    def reclaim(self):
        self.deployer.reclaim()
        self._setup_kubeconfig()

    def collect_logs(self):
        if self.deployer.bootstrap_vm:
            self.deployer.collect_bootstrap_vm_logs()
        self.collect_linux_logs()
        self.collect_windows_logs()

    def collect_windows_logs(self):
        if "KUBECONFIG" not in os.environ:
            self.logging.info("Skipping collection of Windows logs, because "
                              "KUBECONFIG is not set.")
            return
        local_script_path = os.path.join(
            self.e2e_runner_dir, "scripts/collect-logs.ps1")
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

    def collect_linux_logs(self):
        if "KUBECONFIG" not in os.environ:
            self.logging.info("Skipping collection of Linux logs, because "
                              "KUBECONFIG is not set.")
            return
        local_script_path = os.path.join(
            self.e2e_runner_dir, "scripts/collect-logs.sh")
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

    def set_patches(self, patches=[]):
        self.patches = patches

    def _setup_kubetest(self):
        self.logging.info("Setup Kubetest")
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=['mkdir -p {}'.format(
                os.path.dirname(self.deployer.remote_test_infra_path))])
        self.deployer.remote_clone_git_repo(
            'https://github.com/kubernetes/test-infra.git',
            'master',
            self.deployer.remote_test_infra_path)
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=['GO111MODULE=on go install ./kubetest'],
            cwd=self.deployer.remote_test_infra_path)
        local_gopath_bin_path = os.path.join(utils.get_go_path(), "bin")
        os.makedirs(local_gopath_bin_path, exist_ok=True)
        self.deployer.download_from_bootstrap_vm(
            '{}/bin/kubetest'.format(self.deployer.remote_go_path),
            '{}/kubetest'.format(local_gopath_bin_path))

    def _setup_e2e_tests(self):
        self.logging.info("Setup Kubernetes E2E tests")
        self.deployer.remote_clone_git_repo(
            self.opts.k8s_repo, self.opts.k8s_branch,
            self.deployer.remote_k8s_path)
        self.logging.info("Building tests")
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=['make WHAT="test/e2e/e2e.test"'],
            cwd=self.deployer.remote_k8s_path)
        self.logging.info("Building ginkgo")
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=['make WHAT="vendor/github.com/onsi/ginkgo/ginkgo"'],
            cwd=self.deployer.remote_k8s_path)
        local_k8s_path = utils.get_k8s_folder()
        os.makedirs(local_k8s_path, exist_ok=True)
        self.deployer.download_from_bootstrap_vm(
            "{}/".format(self.deployer.remote_k8s_path), local_k8s_path)

    def _prepare_tests(self):
        kubectl = utils.get_kubectl_bin()
        out, _ = utils.run_shell_cmd([
            kubectl, "get", "nodes", "--selector",
            "beta.kubernetes.io/os=linux", "--no-headers", "-o",
            "custom-columns=NAME:.metadata.name"
        ])
        linux_nodes = out.decode().strip().split("\n")
        for node in linux_nodes:
            utils.run_shell_cmd([
                kubectl, "taint", "nodes", "--overwrite", node,
                "node-role.kubernetes.io/master=:NoSchedule"
            ])
            utils.run_shell_cmd([
                kubectl, "label", "nodes", "--overwrite", node,
                "node-role.kubernetes.io/master=NoSchedule"
            ])
        self.logging.info("Downloading repo-list")
        utils.download_file(self.opts.repo_list, "/tmp/repo-list")
        os.environ["KUBE_TEST_REPO_LIST"] = "/tmp/repo-list"

    def _install_patches(self):
        if len(self.patches) == 0:
            return
        self.logging.info("Installing patches")
        patches = " ".join(self.patches)
        local_script_path = os.path.join(
            self.e2e_runner_dir, "scripts/install-patches.ps1")
        node_addresses = self.deployer.windows_private_addresses
        self._upload_to(
            local_script_path, "/tmp/install-patches.ps1", node_addresses)
        async_cmds = []
        for node_address in node_addresses:
            cmd_args = [node_address, "/tmp/install-patches.ps1", patches]
            log_prefix = "%s : " % node_address
            async_cmds.append(
                utils.run_async_shell_cmd(sh.ssh, cmd_args, log_prefix))
        for async_cmd in async_cmds:
            async_cmd.wait()
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
        for attempt in Retrying(
                stop=stop_after_delay(timeout),
                wait=wait_exponential(max=30),
                retry=retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                all_ready = True
                for addr in node_addresses:
                    is_ready = self.deployer.check_k8s_node_connection(addr)
                    if not is_ready:
                        self.logging.warning("Node %s is not up yet", addr)
                        all_ready = False
                assert all_ready
            self.logging.info("All the nodes are up")

    def _prepare_test_env(self):
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
        utils.retry_on_error()(utils.run_shell_cmd)(
            [self.kubectl, "apply", "-f", prepull_yaml_path])
        self.logging.info(
            "Waiting up to %.2f minutes to pre-pull Windows container images",
            timeout / 60.0)
        cmd = [self.kubectl, "get", "-o", "yaml", "-f", prepull_yaml_path]
        for attempt in Retrying(
                stop=stop_after_delay(timeout),
                wait=wait_exponential(max=30),
                retry=retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                output, _ = utils.run_shell_cmd(cmd, sensitive=True)
                ds = yaml.safe_load(output.decode())
                ready_nr = ds["status"]["numberReady"]
                desired_ready_nr = ds["status"]["desiredNumberScheduled"]
                assert ready_nr == desired_ready_nr
        self.logging.info("Windows images successfully pre-pulled")
        self.logging.info("Cleaning up")
        utils.retry_on_error()(utils.run_shell_cmd)(
            [self.kubectl, "delete", "--wait", "-f", prepull_yaml_path])

    def _validate_cluster(self):
        self.logging.info("Validating cluster")
        self._validate_k8s_api_versions()
        self._validate_k8s_api_container_images()

    def _validate_k8s_api_versions(self):
        self.logging.info("Validating K8s API versions")
        output, _ = utils.retry_on_error()(
            utils.run_shell_cmd)([self.kubectl, "get", "nodes", "-o", "yaml"])
        nodes = yaml.safe_load(output.decode())
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
        nodes = yaml.safe_load(output.decode())
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
        utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "wait", "--for=condition=Ready", "--timeout", "30m",
            "pods", "--all", "--all-namespaces"
        ])

    def _upload_kube_proxy_windows_bin(self):
        self.logging.info("Uploading the kube-proxy.exe to the Windows agents")
        win_node_addresses = self.deployer.windows_private_addresses
        kube_proxy_bin = "%s/%s/kube-proxy.exe" % (
            utils.get_k8s_folder(),
            constants.KUBERNETES_WINDOWS_BINS_LOCATION)
        self._run_remote_cmd("mkdir -force /build", win_node_addresses)
        self._upload_to(
            kube_proxy_bin, "/build/kube-proxy.exe", win_node_addresses)

    def _allocate_win_source_vip(self):
        self.logging.info("Allocating source VIP for the Windows agents")
        local_script_path = os.path.join(
            self.e2e_runner_dir, "scripts/allocate-source-vip.ps1")
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
            self.e2e_runner_dir, "scripts/confirm-ready-cni.ps1")
        remote_script_path = "/tmp/confirm-ready-cni.ps1"
        self._upload_to(
            local_script_path, remote_script_path, win_node_addresses)
        for attempt in Retrying(
                stop=stop_after_delay(timeout),
                wait=wait_exponential(max=30),
                retry=retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                cni_ready = True
                for node_address in win_node_addresses:
                    try:
                        stdout = subprocess.check_output(
                            ["ssh", node_address, remote_script_path],
                            timeout=30)
                    except Exception:
                        cni_ready = False
                        break
                    cni_ready = strtobool(stdout.decode().strip())
                    if not cni_ready:
                        break
                assert cni_ready
        self.logging.info("The CNI is ready on all the Windows agents")

    def _add_kube_proxy_windows(self):
        template_file = os.path.join(
            self.capz_flannel_dir, "kube-proxy/kube-proxy-windows.yaml.j2")
        server_core_tag = "windowsservercore-%s" % (
            self.opts.base_container_image_tag)
        context = {
            "kubernetes_version": self.kubernetes_version,
            "server_core_tag": server_core_tag,
            "enable_win_dsr": str(self.opts.enable_win_dsr).lower(),
            "flannel_mode": self.opts.flannel_mode
        }
        output_file = "/tmp/kube-proxy-windows.yaml"
        utils.render_template(template_file, output_file, context)
        cmd = [self.kubectl, "apply", "-f", output_file]
        utils.retry_on_error()(utils.run_shell_cmd)(cmd)

    def _add_flannel_cni(self):
        template_file = os.path.join(
            self.capz_flannel_dir, "flannel/kube-flannel.yaml.j2")
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
        searchpath = os.path.join(self.capz_flannel_dir, "flannel")
        utils.render_template("kube-flannel-windows.yaml.j2",
                              kube_flannel_windows, context, searchpath)
        cmd = [self.kubectl, "apply", "-f", kube_flannel]
        utils.retry_on_error()(utils.run_shell_cmd)(cmd)
        cmd = [self.kubectl, "apply", "-f", kube_flannel_windows]
        utils.retry_on_error()(utils.run_shell_cmd)(cmd)

    def _setup_kubeconfig(self):
        os.environ["KUBECONFIG"] = self.deployer.capz_kubeconfig_path

    def _build_k8s_artifacts(self):
        local_k8s_path = utils.get_k8s_folder()
        remote_k8s_path = self.deployer.remote_k8s_path
        self.deployer.remote_clone_git_repo(
            self.opts.k8s_repo, self.opts.k8s_branch, remote_k8s_path)
        self.logging.info("Building K8s Linux binaries")
        cmd = ('make '
               'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm" '
               'KUBE_BUILD_PLATFORMS="linux/amd64"')
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        del os.environ["KUBECTL_PATH"]
        self.logging.info("Building K8s Windows binaries")
        cmd = ('make '
               'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm cmd/kube-proxy" '
               'KUBE_BUILD_PLATFORMS="windows/amd64"')
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        os.makedirs(local_k8s_path, exist_ok=True)
        self.deployer.download_from_bootstrap_vm(
            "{}/".format(remote_k8s_path), local_k8s_path)
        self.logging.info("Building K8s Linux DaemonSet container images")
        cmd = ("KUBE_FASTBUILD=true KUBE_BUILD_CONFORMANCE=n make "
               "quick-release-images")
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        kubeadm_bin = os.path.join(constants.KUBERNETES_LINUX_BINS_LOCATION,
                                   'kubeadm')
        out, _ = utils.run_shell_cmd(
            [kubeadm_bin, "version", "-o=short"], local_k8s_path)
        self.ci_version = out.decode().strip()
        self.deployer.ci_version = self.ci_version
        self.logging.info("Copying binaries to remote artifacts directory")
        linux_bin_dir = "%s/%s/bin/linux/amd64" % (
            self.deployer.remote_artifacts_dir, self.ci_version)
        windows_bin_dir = "%s/%s/bin/windows/amd64" % (
            self.deployer.remote_artifacts_dir, self.ci_version)
        images_dir = "%s/%s/images" % (
            self.deployer.remote_artifacts_dir, self.ci_version)
        script = [
            "mkdir -p {0} {1} {2}".format(
                linux_bin_dir, windows_bin_dir, images_dir)]
        for bin_name in ["kubectl", "kubelet", "kubeadm"]:
            linux_bin_path = "%s/%s/%s" % (
                remote_k8s_path,
                constants.KUBERNETES_LINUX_BINS_LOCATION,
                bin_name)
            script.append("cp {0} {1}".format(linux_bin_path, linux_bin_dir))
        for bin_name in ["kubectl", "kubelet", "kubeadm", "kube-proxy"]:
            win_bin_path = "%s/%s/%s.exe" % (
                remote_k8s_path,
                constants.KUBERNETES_WINDOWS_BINS_LOCATION,
                bin_name)
            script.append("cp {0} {1}".format(win_bin_path, windows_bin_dir))
        images_names = [
            "kube-apiserver.tar", "kube-controller-manager.tar",
            "kube-proxy.tar", "kube-scheduler.tar"
        ]
        for image_name in images_names:
            image_path = "%s/%s/%s" % (
                remote_k8s_path,
                constants.KUBERNETES_IMAGES_LOCATION,
                image_name)
            script.append("cp {0} {1}".format(image_path, images_dir))
        script.append("chmod 644 {0}/*".format(images_dir))
        self.deployer.run_cmd_on_bootstrap_vm(script)
        self._setup_e2e_tests()
        self._setup_kubetest()

    def _build_containerd_binaries(self):
        # Clone the git repositories
        remote_containerd_path = self.deployer.remote_containerd_path
        self.deployer.remote_clone_git_repo(
            self.opts.containerd_repo, self.opts.containerd_branch,
            remote_containerd_path)
        remote_cri_tools_path = os.path.join(
            self.deployer.remote_go_path,
            "src", "github.com", "kubernetes-sigs", "cri-tools")
        self.deployer.remote_clone_git_repo(
            self.opts.cri_tools_repo, self.opts.cri_tools_branch,
            remote_cri_tools_path)
        # Build the binaries
        self.logging.info("Building containerd binaries")
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=["GOOS=windows make binaries"], cwd=remote_containerd_path)
        self.logging.info("Building crictl")
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=["GOOS=windows make crictl"], cwd=remote_cri_tools_path)
        # Copy the binaries to the artifacts directory
        self.logging.info("Copying binaries to remote artifacts directory")
        artifacts_containerd_bin_dir = os.path.join(
            self.deployer.remote_artifacts_dir, "containerd/bin")
        script = ["mkdir -p {0}".format(artifacts_containerd_bin_dir)]
        containerd_bins = os.path.join(remote_containerd_path, "bin")
        script.append("cp {0}/* {1}".format(
            containerd_bins, artifacts_containerd_bin_dir))
        crictl_bin = os.path.join(
            remote_cri_tools_path, "build/bin/crictl.exe")
        script.append("cp {0} {1}".format(
            crictl_bin, artifacts_containerd_bin_dir))
        self.deployer.run_cmd_on_bootstrap_vm(script)

    def _build_containerd_shim(self):
        remote_containerd_shim_path = self.deployer.remote_containerd_shim_path
        self.deployer.remote_clone_git_repo(
            self.opts.containerd_shim_repo,
            self.opts.containerd_shim_branch, remote_containerd_shim_path)
        self.logging.info("Building containerd shim")
        build_cmd = ("GOOS=windows GO111MODULE=on "
                     "go build -mod=vendor -o {0} {1}".format(
                         constants.CONTAINERD_SHIM_BIN,
                         constants.CONTAINERD_SHIM_DIR))
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=[build_cmd], cwd=remote_containerd_shim_path)
        self.logging.info("Copying binaries to remote artifacts directory")
        artifacts_containerd_bin_dir = os.path.join(
            self.deployer.remote_artifacts_dir, "containerd/bin")
        script = ["mkdir -p {0}".format(artifacts_containerd_bin_dir)]
        containerd_shim_bin = os.path.join(remote_containerd_shim_path,
                                           constants.CONTAINERD_SHIM_BIN)
        script.append("cp {0} {1}".format(
            containerd_shim_bin, artifacts_containerd_bin_dir))
        self.deployer.run_cmd_on_bootstrap_vm(script)

    def _build_sdn_cni_binaries(self):
        remote_sdn_cni_dir = self.deployer.remote_sdn_path
        self.deployer.remote_clone_git_repo(
            self.opts.sdn_repo, self.opts.sdn_branch, remote_sdn_cni_dir)
        self.logging.info("Building the SDN CNI binaries")
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=["GOOS=windows make all"], cwd=remote_sdn_cni_dir)
        self.logging.info("Copying binaries to remote artifacts directory")
        artifacts_cni_dir = os.path.join(
            self.deployer.remote_artifacts_dir, "cni")
        script = ["mkdir -p {0}".format(artifacts_cni_dir)]
        sdn_binaries_names = ["nat.exe", "sdnbridge.exe", "sdnoverlay.exe"]
        for sdn_bin_name in sdn_binaries_names:
            sdn_bin = os.path.join(remote_sdn_cni_dir, "out", sdn_bin_name)
            script.append("cp {0} {1}".format(sdn_bin, artifacts_cni_dir))
        self.deployer.run_cmd_on_bootstrap_vm(script)

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
        node_name = node_name.decode().strip()
        local_logs_archive = os.path.join(
            self.opts.artifacts_directory,
            "%s-%s" % (node_name, os.path.basename(remote_logs_archive)))
        self.deployer.download_from_k8s_node(
            remote_logs_archive, local_logs_archive, node_address)
        self.logging.info("Finished collecting logs from node %s",
                          node_name)
