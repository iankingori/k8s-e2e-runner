import os
import time
import yaml
import json

import tenacity

from datetime import datetime

from e2e_runner import base as e2e_base
from e2e_runner import logger as e2e_logger
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
        self._create_metadata_artifact()
        self.deployer.up()
        self._setup_kubeconfig()
        self._add_flannel_cni()
        self.deployer.wait_windows_agents()
        self.deployer.setup_ssh_config()
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
        remote_logs_archive = "/tmp/logs.tgz"
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
        remote_logs_archive = "/tmp/logs.tgz"
        for node_address in self.deployer.linux_private_addresses:
            try:
                self._collect_logs(
                    node_address, local_script_path, remote_script_path,
                    remote_cmd, remote_logs_archive)
            except Exception as ex:
                self.logging.warning(
                    "Cannot collect logs from node %s. Exception details: "
                    "%s. Skipping", node_address, ex)

    def _create_metadata_artifact(self):
        metadata_path = os.path.join(
            self.opts.artifacts_directory, "metadata.json")
        metadata = {
            "job-version": self.kubernetes_version,
            "revision": self.kubernetes_version,
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

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

    def _conformance_image_tag(self):
        if "k8sbins" in self.deployer.bins_built:
            return self.kubernetes_version.replace("+", "_")
        return self.kubernetes_version

    def _conformance_image_pull_cmd(self):
        if "k8sbins" in self.deployer.bins_built:
            # Image is already imported as part of the userdata script.
            return ""
        cmd = [
            "sudo", "ctr", "-n", "k8s.io",
            "image", "pull",
            f"k8s.gcr.io/conformance:{self._conformance_image_tag()}"
        ]
        return " ".join(cmd)

    def _conformance_tests_cmd(self):
        cmd = ["sudo", "ctr", "-n", "k8s.io", "run", "--rm", "--net-host"]
        mounts = [
            {
                "src": "/tmp/output",
                "dst": "/output",
                "mode": "rw",
            },
            {
                "src": "/tmp/repo-list",
                "dst": "/tmp/repo-list",
                "mode": "ro",
            },
            {
                "src": "/etc/kubernetes/admin.conf",
                "dst": "/tmp/kubeconfig",
                "mode": "ro",
            },
        ]
        env = {
            "KUBE_TEST_REPO_LIST": "/tmp/repo-list",
        }
        ginkgoFlags = {
            "noColor": "true",
            "progress": "true",
            "trace": "true",
            "v": "true",
            "slowSpecThreshold": "120.0",
            "nodes": self.opts.parallel_test_nodes,
            "focus": f"'{self.opts.test_focus_regex}'",
            "skip": f"'{self.opts.test_skip_regex}'",
        }
        e2eFlags = {
            "kubeconfig": "/tmp/kubeconfig",
            "provider": "skeleton",
            "report-dir": "/output",
            "e2e-output-dir": "/output/e2e-output",
            "test.timeout": "2h",
            "num-nodes": "2",
            "node-os-distro": "windows",
            "prepull-images": "true",
            "disable-log-dump": "true",
        }
        docker_config_file = os.environ.get("DOCKER_CONFIG_FILE")
        if docker_config_file:
            mounts.append({
                "src": "/tmp/docker-creds-config.json",
                "dst": "/tmp/docker-creds-config.json",
                "mode": "ro",
            })
            e2eFlags["docker-config-file"] = "/tmp/docker-creds-config.json"
        for m in mounts:
            src = m["src"]
            dst = m["dst"]
            mode = m.get("mode", "rw")
            opts = f"rbind:{mode}"
            cmd.extend([
                "--mount",
                f"type=bind,src={src},dst={dst},options={opts}"
            ])
        for key in env:
            cmd.extend([
                "--env",
                f"{key}={env[key]}"
            ])
        ginkgoArgs = [f"--{k}={v}" for k, v in ginkgoFlags.items()]
        e2eArgs = [f"--{k}={v}" for k, v in e2eFlags.items()]
        cmd.extend([
            f"k8s.gcr.io/conformance:{self._conformance_image_tag()}",
            "conformance_tests",
            "/usr/local/bin/ginkgo",
            *ginkgoArgs,
            "/usr/local/bin/e2e.test",
            "--",
            *e2eArgs,
        ])
        return " ".join(cmd)

    def _prepare_tests(self):
        self._label_linux_nodes_no_schedule()
        self._prepull_images()
        self.logging.info("Downloading repo-list")
        e2e_utils.download_file(self.opts.repo_list, "/tmp/repo-list")
        self._upload_to_node(
            "/tmp/repo-list", "/tmp/repo-list",
            [self.deployer.master_public_address])
        self._run_node_cmd(
            "mkdir -p /tmp/output",
            [self.deployer.master_public_address])
        docker_config_file = os.environ.get("DOCKER_CONFIG_FILE")
        if docker_config_file:
            self._upload_to_node(
                docker_config_file, "/tmp/docker-creds-config.json",
                [self.deployer.master_public_address])

    def _run_tests(self):
        ssh_kwargs = {
            "ssh_user": "capi",
            "ssh_address": self.deployer.master_public_address,
            "ssh_key_path": os.environ["SSH_KEY"],
        }
        tests_cmd = [
            self._conformance_image_pull_cmd(),
            self._conformance_tests_cmd(),
        ]
        tests_timeout = 150 * 60  # 150 minutes
        try:
            self.logging.info("Tests cmd\n%s", "\n".join(tests_cmd))
            e2e_utils.run_remote_ssh_cmd(
                cmd=tests_cmd, timeout=tests_timeout, **ssh_kwargs)
        except Exception:
            return 1
        finally:
            e2e_utils.rsync_download(
                "/tmp/output/", self.opts.artifacts_directory,
                delete=False, **ssh_kwargs)
        return 0

    def _upload_to_node(self, local_path, remote_path, node_addresses):
        for node_address in node_addresses:
            self.deployer.upload_to_k8s_node(
                local_path, remote_path, node_address)

    def _run_node_cmd(self, cmd, node_addresses):
        for node_address in node_addresses:
            self.deployer.run_cmd_on_k8s_node(cmd, node_address)

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

    def _add_kube_proxy_windows(self):
        context = {
            "kubernetes_version": self.deployer.k8s_image_version,
            "container_runtime": self.opts.container_runtime,
            "win_os": self.opts.win_os,
            "container_image_tag": self.opts.container_image_tag,
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
            "container_image_tag": self.opts.container_image_tag,
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
        remote_k8s_path = self.deployer.remote_k8s_path
        self.deployer.remote_clone_git_repo(
            self.opts.k8s_repo, self.opts.k8s_branch, remote_k8s_path)
        # Build Linux binaries
        self.logging.info("Building K8s Linux binaries")
        cmd = ('make '
               'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm" '
               'KUBE_BUILD_PLATFORMS="linux/amd64"')
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        # Build Windows binaries
        self.logging.info("Building K8s Windows binaries")
        cmd = ('make '
               'WHAT="cmd/kubectl cmd/kubelet cmd/kubeadm cmd/kube-proxy" '
               'KUBE_BUILD_PLATFORMS="windows/amd64"')
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        # Build Linux DaemonSet container images
        self.logging.info("Building K8s Linux DaemonSet container images")
        cmd = ("KUBE_FASTBUILD=true KUBE_BUILD_CONFORMANCE=y "
               "make quick-release-images")
        self.deployer.run_cmd_on_bootstrap_vm([cmd], cwd=remote_k8s_path)
        # Discover the K8s version built
        kubeadm_bin = os.path.join(
            remote_k8s_path, "_output/local/bin/linux/amd64/kubeadm")
        out, _ = self.deployer.run_cmd_on_bootstrap_vm(
            cmd=[f"{kubeadm_bin} version -o=short"],
            timeout=30, return_result=True)
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
            "kube-proxy.tar", "kube-scheduler.tar", "conformance-amd64.tar"
        ]
        for image_name in images_names:
            image_path = "{}/{}/{}".format(
                remote_k8s_path,
                "_output/release-images/amd64",
                image_name)
            script.append(f"cp {image_path} {images_dir}")
        script.append(
            "mv "
            f"{images_dir}/conformance-amd64.tar "
            f"{images_dir}/conformance.tar")
        script.append(f"chmod 644 {images_dir}/*")
        self.deployer.run_cmd_on_bootstrap_vm(script)

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
