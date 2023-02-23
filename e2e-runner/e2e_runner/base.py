import json
import os
import shutil

from e2e_runner import constants as e2e_constants
from e2e_runner import exceptions as e2e_exceptions
from e2e_runner import logger as e2e_logger
from e2e_runner.utils import kubernetes as e2e_k8s_utils
from e2e_runner.utils import utils as e2e_utils


class CI(object):
    HELPER_POD = "alpine"
    CONFORMANCE_POD = "conformance-tests"
    JUMPBOX_POD = "jumpbox"

    def __init__(self, opts):
        self.e2e_runner_dir = os.path.dirname(__file__)
        self.logging = e2e_logger.get_logger(__name__)
        self.opts = opts
        self.kubernetes_version = e2e_constants.DEFAULT_KUBERNETES_VERSION
        self.kubeconfig_dir = os.path.join(os.environ["HOME"], ".kube")
        self.kubeconfig_path = os.path.join(self.kubeconfig_dir, "config")
        self.ssh_private_key_path = os.environ["SSH_PRIVATE_KEY_PATH"]

    @property
    def k8s_client(self):
        return e2e_k8s_utils.KubernetesClient(config_file=self.kubeconfig_path)

    def setup_bootstrap_vm(self):
        pass

    def cleanup_bootstrap_vm(self):
        pass

    def build(self, _):
        pass

    def up(self):
        pass

    def down(self):
        pass

    def test(self):
        self._prepare_tests()
        return self._run_tests()

    def collect_logs(self):
        pass

    def _create_metadata_artifact(self):
        metadata_path = os.path.join(
            self.opts.artifacts_directory, "metadata.json")
        metadata = {
            "job-version": self.kubernetes_version,
            "revision": self.kubernetes_version,
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

    def _prepare_tests(self):
        self._setup_repo_list_configmap()
        self._setup_private_registry_secret()

    def _run_tests(self):
        self._start_conformance_tests()
        self.k8s_client.watch_pod_log(self.CONFORMANCE_POD)

        e2e_utils.download_from_pod(
            self.HELPER_POD, "output", self.opts.artifacts_directory)

        pod_phase = self.k8s_client.get_pod_phase(self.CONFORMANCE_POD)
        if pod_phase != "Succeeded":
            raise e2e_exceptions.ConformanceTestsFailed(
                "The end-to-end conformance tests failed")

    def _setup_repo_list_configmap(self):
        repo_list_file = "/tmp/repo-list.yaml"
        e2e_utils.download_file(self.opts.repo_list, repo_list_file)
        self.k8s_client.create_configmap_from_file(
            "repo-list", repo_list_file, config_map_file_name="repos.yaml")

    def _setup_private_registry_secret(self):
        docker_config_file = os.environ.get("DOCKER_CONFIG_FILE")
        if not docker_config_file:
            return
        self.k8s_client.create_secret_from_file(
            "docker-creds", docker_config_file, secret_file_name="config.json")

    def _start_conformance_tests(self):
        ginkgo_flags, e2e_flags = self._conformance_tests_flags()
        ctxt = {
            'conformance_image': self._conformance_image(),
            'ginkgo_flags': ginkgo_flags,
            'e2e_flags': e2e_flags,
        }
        if self.opts.e2e_bin:
            ctxt["e2e_bin_url"] = self.opts.e2e_bin
        output_file = "/tmp/conformance.yaml"
        e2e_utils.render_template("templates/conformance.yaml.j2", output_file,
                                  ctxt, self.e2e_runner_dir)
        self.k8s_client.create_from_yaml(output_file)
        self.k8s_client.wait_running_pod(self.HELPER_POD)
        self.k8s_client.wait_running_pod(self.CONFORMANCE_POD)

    def _conformance_image(self):
        tag = self.kubernetes_version.replace("+", "_")
        return f"registry.k8s.io/conformance:{tag}"

    def _conformance_nodes_non_blocking_taints(self):
        return []

    def _conformance_tests_flags(self, num_nodes="2", node_os_distro="windows",
                                 output_dir="/output"):
        ginkgoFlags = {
            "trace": "true",
            "v": "true",
            "nodes": self.opts.parallel_test_nodes,
            "focus": self.opts.test_focus_regex,
            "skip": self.opts.test_skip_regex,
        }
        if self.kubernetes_version >= "v1.27":
            ginkgoFlags["show-node-events"] = "true"
            ginkgoFlags["poll-progress-after"] = "5m"
        else:
            ginkgoFlags["progress"] = "true"
            if self.kubernetes_version >= "v1.25":
                ginkgoFlags["no-color"] = "true"
                ginkgoFlags["slow-spec-threshold"] = "5m"
            else:
                ginkgoFlags["noColor"] = "true"
                ginkgoFlags["slowSpecThreshold"] = "300.0"

        e2eFlags = {
            "provider": "skeleton",
            "report-dir": output_dir,
            "e2e-output-dir": f"{output_dir}/e2e-output",
            "num-nodes": num_nodes,
            "node-os-distro": node_os_distro,
            "test.timeout": "2h",
            "prepull-images": "true",
            "disable-log-dump": "true",
        }
        non_blocking_taints = self._conformance_nodes_non_blocking_taints()
        if len(non_blocking_taints) > 0:
            e2eFlags["non-blocking-taints"] = ",".join(non_blocking_taints)
        if os.environ.get("DOCKER_CONFIG_FILE"):
            e2eFlags["docker-config-file"] = "/docker-creds/config.json"

        return ginkgoFlags, e2eFlags

    def _jumpbox_exec_ssh(self, user, address, cmd):
        ssh_opts = [
            "StrictHostKeyChecking=no",
            "UserKnownHostsFile=/dev/null",
        ]
        ssh_opts_args = [f"-o {opt}" for opt in ssh_opts]
        ssh_cmd = ["ssh", *ssh_opts_args, f"{user}@{address}", *cmd]
        e2e_utils.exec_pod(self.JUMPBOX_POD, ssh_cmd)

    def _jumpbox_exec_scp(self, user, address, file_path, remote_file_path):
        ssh_opts = [
            "StrictHostKeyChecking=no",
            "UserKnownHostsFile=/dev/null",
        ]
        ssh_opts_args = [f"-o {opt}" for opt in ssh_opts]
        scp_cmd = [
            "scp",
            *ssh_opts_args,
            file_path, f"{user}@{address}:{remote_file_path}",
        ]
        e2e_utils.exec_pod(self.JUMPBOX_POD, scp_cmd)

    def _setup_jumpbox(self):
        manifest_file = os.path.join(
            self.e2e_runner_dir, "templates/jumpbox.yaml")
        self.k8s_client.create_from_yaml(manifest_file)
        self.k8s_client.wait_running_pod(self.JUMPBOX_POD)
        e2e_utils.exec_pod(self.JUMPBOX_POD, ["apk", "add", "openssh-client"])
        e2e_utils.exec_pod(self.JUMPBOX_POD, ["mkdir", "-p", "/root/.ssh"])
        # Make sure that 'self.ssh_private_key_path' is not a symlink before
        # trying to upload it to pod via 'upload_to_pod'. The utils function
        # 'upload_to_pod' uses 'kubectl cp', and it doesn't follow symlinks.
        shutil.copy2(
            self.ssh_private_key_path, "/tmp/id_rsa", follow_symlinks=True)
        e2e_utils.upload_to_pod(
            self.JUMPBOX_POD, "/tmp/id_rsa", "/root/.ssh/id_rsa")

    def _remove_jumpbox(self):
        self.k8s_client.delete_pod(self.JUMPBOX_POD)
