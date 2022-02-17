import os
import time
import yaml

import tenacity

from datetime import datetime

from e2e_runner import base as e2e_base
from e2e_runner import logger as e2e_logger
from e2e_runner import constants as e2e_constants
from e2e_runner import utils as e2e_utils

from e2e_runner.deployer.capz import capz


class CapzFlannelCI(e2e_base.CI):

    def __init__(self, opts):
        super(CapzFlannelCI, self).__init__(opts)

        self.capz_flannel_dir = os.path.dirname(__file__)
        self.logging = e2e_logger.get_logger(__name__)

        self.kubectl = e2e_utils.get_kubectl_bin()
        self.kubernetes_version = self.opts.kubernetes_version

        self.deployer = capz.CAPZProvisioner(
            opts, resource_group_tags=self.resource_group_tags)

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

    def setup_bootstrap_vm(self):
        return self.deployer.setup_bootstrap_vm()

    def cleanup_bootstrap_vm(self):
        return self.deployer.cleanup_bootstrap_vm()

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
        self._setup_kubeconfig()
        self._add_flannel_cni()
        self.deployer.wait_windows_agents()
        self.deployer.setup_ssh_config()
        if "k8sbins" in self.deployer.bins_built:
            self._upload_kube_proxy_windows_bin()
        self._add_kube_proxy_windows()
        self._wait_for_ready_pods()
        elapsed = time.time() - start
        self.logging.info(
            "The cluster provisioned in %.2f minutes", elapsed / 60)
        self._validate_k8s_api_versions()

    def down(self):
        self.deployer.down()

    def collect_logs(self):
        if self.deployer.bootstrap_vm:
            self.deployer.collect_bootstrap_vm_logs()
        self.collect_linux_logs()
        self.collect_windows_logs()

    def collect_windows_logs(self):
        if not self._can_collect_logs():
            self.logging.info("Skipping logs collection.")
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
        if not self._can_collect_logs():
            self.logging.info("Skipping logs collection.")
            return
        local_script_path = os.path.join(
            self.e2e_runner_dir, "scripts/collect-logs.sh")
        remote_script_path = os.path.join(
            "/tmp", os.path.basename(local_script_path))
        remote_cmd = f"sudo bash {remote_script_path}"
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

    def _can_collect_logs(self):
        if "KUBECONFIG" not in os.environ:
            self.logging.warning(
                "Cannot collect logs, because KUBECONFIG is not set.")
            return False
        ssh_config = os.path.join(os.environ["HOME"], ".ssh/config")
        if not os.path.exists(ssh_config):
            self.logging.warning(
                "Cannot collect logs, because the ssh config file is not set.")
            return False
        return True

    def _setup_kubeconfig(self):
        os.environ["KUBECONFIG"] = self.deployer.capz_kubeconfig_path

    def _setup_kubetest(self):
        self.logging.info("Setup Kubetest")
        remote_dirname = os.path.dirname(self.deployer.remote_test_infra_path)
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=[f"mkdir -p {remote_dirname}"])
        self.deployer.remote_clone_git_repo(
            "https://github.com/kubernetes/test-infra.git",
            "master",
            self.deployer.remote_test_infra_path)
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=['GO111MODULE=on go install ./kubetest'],
            cwd=self.deployer.remote_test_infra_path)
        local_gopath_bin_path = os.path.join(e2e_utils.get_go_path(), "bin")
        os.makedirs(local_gopath_bin_path, exist_ok=True)
        self.deployer.download_from_bootstrap_vm(
            f"{self.deployer.remote_go_path}/bin/kubetest",
            f"{local_gopath_bin_path}/kubetest")

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
        local_k8s_path = e2e_utils.get_k8s_folder()
        os.makedirs(local_k8s_path, exist_ok=True)
        self.deployer.download_from_bootstrap_vm(
            f"{self.deployer.remote_k8s_path}/", local_k8s_path)

    def _prepare_tests(self):
        kubectl = e2e_utils.get_kubectl_bin()
        out, _ = e2e_utils.run_shell_cmd([
            kubectl, "get", "nodes", "--selector",
            "beta.kubernetes.io/os=linux", "--no-headers", "-o",
            "custom-columns=NAME:.metadata.name"
        ])
        linux_nodes = out.decode().strip().split("\n")
        for node in linux_nodes:
            e2e_utils.run_shell_cmd([
                kubectl, "taint", "nodes", "--overwrite", node,
                "node-role.kubernetes.io/master=:NoSchedule"
            ])
            e2e_utils.run_shell_cmd([
                kubectl, "label", "nodes", "--overwrite", node,
                "node-role.kubernetes.io/master=NoSchedule"
            ])
        self.logging.info("Downloading repo-list")
        e2e_utils.download_file(self.opts.repo_list, "/tmp/repo-list")
        os.environ["KUBE_TEST_REPO_LIST"] = "/tmp/repo-list"

    def _upload_to_node(self, local_path, remote_path, node_addresses):
        for node_address in node_addresses:
            self.deployer.upload_to_k8s_node(
                local_path, remote_path, node_address)

    def _run_node_cmd(self, cmd, node_addresses):
        for node_address in node_addresses:
            self.deployer.run_cmd_on_k8s_node(cmd, node_address)

    def _prepare_test_env(self):
        self.logging.info("Preparing test env")
        os.environ["KUBE_MASTER"] = "local"
        os.environ["KUBE_MASTER_IP"] = self.deployer.master_public_address
        os.environ["KUBE_MASTER_URL"] = "https://{}:{}".format(
            self.deployer.master_public_address,
            self.deployer.master_public_port)
        self._prepull_images()

    def _prepull_images(self, timeout=3600):
        prepull_yaml_path = "/tmp/prepull-windows-images.yaml"
        e2e_utils.download_file(self.opts.prepull_yaml, prepull_yaml_path)
        self.logging.info("Starting Windows images pre-pull")
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
            self.kubectl, "apply", "-f", prepull_yaml_path])
        self.logging.info(
            "Waiting up to %.2f minutes to pre-pull Windows container images",
            timeout / 60.0)
        cmd = [self.kubectl, "get", "-o", "yaml", "-f", prepull_yaml_path]
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_delay(timeout),
                wait=tenacity.wait_exponential(max=30),
                retry=tenacity.retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                output, _ = e2e_utils.run_shell_cmd(cmd, sensitive=True)
                ds = yaml.safe_load(output.decode())
                ready_nr = ds["status"]["numberReady"]
                desired_ready_nr = ds["status"]["desiredNumberScheduled"]
                assert ready_nr == desired_ready_nr, (
                    f"Windows images pre-pull failed: "
                    f"{ready_nr}/{desired_ready_nr} pods ready.")
        self.logging.info("Windows images successfully pre-pulled")
        self.logging.info("Cleaning up")
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
            self.kubectl, "delete", "--wait", "-f", prepull_yaml_path])

    def _validate_k8s_api_versions(self):
        self.logging.info("Validating K8s API versions")
        output, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
            self.kubectl, "get", "nodes", "-o", "yaml"])
        nodes = yaml.safe_load(output.decode())
        for node in nodes["items"]:
            node_name = node["metadata"]["name"]
            expected_ver = self.kubernetes_version
            kubelet_ver = node["status"]["nodeInfo"]["kubeletVersion"]
            if kubelet_ver != expected_ver:
                raise Exception(
                    f"Wrong kubelet version on node {node_name}. "
                    f"Expected {expected_ver}, but found {kubelet_ver}")
            kube_proxy_ver = node["status"]["nodeInfo"]["kubeProxyVersion"]
            if kube_proxy_ver != expected_ver:
                raise Exception(
                    f"Wrong kube-proxy version on node {node_name}. "
                    f"Expected {expected_ver}, but found {kube_proxy_ver}")

    @e2e_utils.retry_on_error(max_attempts=3)
    def _wait_for_ready_pods(self):
        self.logging.info("Waiting for all the pods to be ready")
        e2e_utils.run_shell_cmd([
            self.kubectl, "wait", "--for=condition=Ready",
            "--timeout", "10m", "pods", "--all", "--all-namespaces"
        ])

    def _upload_kube_proxy_windows_bin(self):
        self.logging.info("Uploading the kube-proxy.exe to the Windows agents")
        win_node_addresses = self.deployer.windows_private_addresses
        kube_proxy_bin = "{}/{}/kube-proxy.exe".format(
            e2e_utils.get_k8s_folder(),
            "_output/local/bin/windows/amd64")
        self._run_node_cmd("mkdir -force /build", win_node_addresses)
        self._upload_to_node(
            kube_proxy_bin, "/build/kube-proxy.exe", win_node_addresses)

    def _add_kube_proxy_windows(self):
        context = {
            "kubernetes_version": e2e_constants.DEFAULT_KUBERNETES_VERSION,
            "container_runtime": self.opts.container_runtime,
            "win_os": self.opts.win_os,
            "enable_win_dsr": str(self.opts.enable_win_dsr).lower(),
            "flannel_mode": self.opts.flannel_mode
        }
        searchpath = os.path.join(
            self.capz_flannel_dir,
            f"kube-proxy/windows/{self.opts.container_runtime}")
        output_file = "/tmp/kube-proxy-windows.yaml"
        e2e_utils.render_template(
            "kube-proxy.yaml.j2", output_file, context, searchpath)
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)(
            [self.kubectl, "apply", "-f", output_file])

    def _add_flannel_cni(self):
        context = {
            "win_os": self.opts.win_os,
            "cluster_network_subnet": self.opts.cluster_network_subnet,
            "flannel_mode": self.opts.flannel_mode,
            "container_runtime": self.opts.container_runtime,
            "control_plane_cidr": self.opts.control_plane_subnet_cidr_block,
            "node_cidr": self.opts.node_subnet_cidr_block,
        }
        searchpath = os.path.join(self.capz_flannel_dir, "flannel")
        kube_flannel = "/tmp/kube-flannel.yaml"
        e2e_utils.render_template(
            "kube-flannel.yaml.j2", kube_flannel, context, searchpath)
        windows_searchpath = os.path.join(
            self.capz_flannel_dir,
            f"flannel/windows/{self.opts.container_runtime}")
        kube_flannel_windows = "/tmp/kube-flannel-windows.yaml"
        e2e_utils.render_template(
            "kube-flannel.yaml.j2", kube_flannel_windows,
            context, windows_searchpath)
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
            self.kubectl, "apply", "-f", kube_flannel])
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)(
            [self.kubectl, "apply", "-f", kube_flannel_windows])

    def _build_k8s_artifacts(self):
        # Clone Kubernetes git repository
        local_k8s_path = e2e_utils.get_k8s_folder()
        remote_k8s_path = self.deployer.remote_k8s_path
        self.deployer.remote_clone_git_repo(
            self.opts.k8s_repo, self.opts.k8s_branch, remote_k8s_path)
        # Build Linux binaries
        self.logging.info("Building K8s Linux binaries")
        cmd = ('make '
               'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm" '
               'KUBE_BUILD_PLATFORMS="linux/amd64"')
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        del os.environ["KUBECTL_PATH"]
        # Build Windows binaries
        self.logging.info("Building K8s Windows binaries")
        cmd = ('make '
               'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm cmd/kube-proxy" '
               'KUBE_BUILD_PLATFORMS="windows/amd64"')
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        # Download binaries from the bootstrap VM
        os.makedirs(local_k8s_path, exist_ok=True)
        self.deployer.download_from_bootstrap_vm(
            f"{remote_k8s_path}/", local_k8s_path)
        # Build Linux DaemonSet container images
        self.logging.info("Building K8s Linux DaemonSet container images")
        cmd = ("KUBE_FASTBUILD=true KUBE_BUILD_CONFORMANCE=n "
               "make quick-release-images")
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        # Discover the K8s version built
        kubeadm_bin = os.path.join(
            local_k8s_path, "_output/local/bin/linux/amd64/kubeadm")
        out, _ = e2e_utils.run_shell_cmd([kubeadm_bin, "version", "-o=short"])
        self.kubernetes_version = out.decode().strip()
        self.deployer.kubernetes_version = self.kubernetes_version
        # Copy artifacts to their own directory on the bootstrap VM
        self.logging.info("Copying K8s artifacts to their own directory")
        linux_bin_dir = "{}/{}/bin/linux/amd64".format(
            self.deployer.remote_artifacts_dir, self.kubernetes_version)
        windows_bin_dir = "{}/{}/bin/windows/amd64".format(
            self.deployer.remote_artifacts_dir, self.kubernetes_version)
        images_dir = "{}/{}/images".format(
            self.deployer.remote_artifacts_dir, self.kubernetes_version)
        script = [f"mkdir -p {linux_bin_dir} {windows_bin_dir} {images_dir}"]
        for bin_name in ["kubectl", "kubelet", "kubeadm"]:
            linux_bin_path = "{}/{}/{}".format(
                remote_k8s_path,
                "_output/local/bin/linux/amd64",
                bin_name)
            script.append(f"cp {linux_bin_path} {linux_bin_dir}")
        for bin_name in ["kubectl", "kubelet", "kubeadm", "kube-proxy"]:
            win_bin_path = "{}/{}/{}.exe".format(
                remote_k8s_path,
                "_output/local/bin/windows/amd64",
                bin_name)
            script.append(f"cp {win_bin_path} {windows_bin_dir}")
        images_names = [
            "kube-apiserver.tar", "kube-controller-manager.tar",
            "kube-proxy.tar", "kube-scheduler.tar"
        ]
        for image_name in images_names:
            image_path = "{}/{}/{}".format(
                remote_k8s_path,
                "_output/release-images/amd64",
                image_name)
            script.append(f"cp {image_path} {images_dir}")
        script.append(f"chmod 644 {images_dir}/*")
        self.deployer.run_cmd_on_bootstrap_vm(script)
        # Setup the E2E tests and the kubetest
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
        script = [f"mkdir -p {artifacts_containerd_bin_dir}"]
        containerd_bins = os.path.join(remote_containerd_path, "bin")
        script.append(f"cp {containerd_bins}/* {artifacts_containerd_bin_dir}")
        crictl_bin = os.path.join(
            remote_cri_tools_path, "build/bin/crictl.exe")
        script.append(f"cp {crictl_bin} {artifacts_containerd_bin_dir}")
        self.deployer.run_cmd_on_bootstrap_vm(script)

    def _build_containerd_shim(self):
        remote_containerd_shim_path = self.deployer.remote_containerd_shim_path
        self.deployer.remote_clone_git_repo(
            self.opts.containerd_shim_repo,
            self.opts.containerd_shim_branch, remote_containerd_shim_path)
        self.logging.info("Building containerd shim")
        build_cmd = (
            "GOOS=windows GO111MODULE=on go build -mod=vendor "
            "-o containerd-shim-runhcs-v1.exe ./cmd/containerd-shim-runhcs-v1")
        self.deployer.run_cmd_on_bootstrap_vm(
            cmd=[build_cmd], cwd=remote_containerd_shim_path)
        self.logging.info("Copying binaries to remote artifacts directory")
        artifacts_containerd_bin_dir = os.path.join(
            self.deployer.remote_artifacts_dir, "containerd/bin")
        script = [f"mkdir -p {artifacts_containerd_bin_dir}"]
        containerd_shim_bin = os.path.join(
            remote_containerd_shim_path, "containerd-shim-runhcs-v1.exe")
        script.append(
            f"cp {containerd_shim_bin} {artifacts_containerd_bin_dir}")
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
        script = [f"mkdir -p {artifacts_cni_dir}"]
        sdn_binaries_names = ["nat.exe", "sdnbridge.exe", "sdnoverlay.exe"]
        for sdn_bin_name in sdn_binaries_names:
            sdn_bin = os.path.join(remote_sdn_cni_dir, "out", sdn_bin_name)
            script.append(f"cp {sdn_bin} {artifacts_cni_dir}")
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
        logs_archive_name = os.path.basename(remote_logs_archive)
        local_logs_archive = os.path.join(
            self.opts.artifacts_directory, f"{node_name}-{logs_archive_name}")
        self.deployer.download_from_k8s_node(
            remote_logs_archive, local_logs_archive, node_address)
        self.logging.info("Finished collecting logs from node %s", node_name)
