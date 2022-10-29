import json
import os

import tenacity
import yaml

from e2e_runner import constants as e2e_constants
from e2e_runner import exceptions as e2e_exceptions
from e2e_runner import logger as e2e_logger
from e2e_runner.utils import kubernetes as e2e_k8s_utils
from e2e_runner.utils import utils as e2e_utils


class CI(object):
    HELPER_POD = "alpine"
    CONFORMANCE_POD = "conformance-tests"

    def __init__(self, opts):
        self.e2e_runner_dir = os.path.dirname(__file__)
        self.logging = e2e_logger.get_logger(__name__)
        self.opts = opts
        self.kubernetes_version = e2e_constants.DEFAULT_KUBERNETES_VERSION
        self.kubeconfig_dir = os.path.join(os.environ["HOME"], ".kube")
        self.kubeconfig_path = os.path.join(self.kubeconfig_dir, "config")

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
        self._prepull_images()
        self._setup_repo_list_configmap()
        self._setup_private_registry_secret()
        e2e_utils.label_linux_nodes_no_schedule()

    def _run_tests(self):
        self._start_conformance_tests()
        self.k8s_client.watch_pod_log(self.CONFORMANCE_POD)

        e2e_utils.download_from_pod(
            self.HELPER_POD, "output", self.opts.artifacts_directory)

        pod_phase = self.k8s_client.get_pod_phase(self.CONFORMANCE_POD)
        if pod_phase != "Succeeded":
            raise e2e_exceptions.ConformanceTestsFailed(
                "The end-to-end conformance tests failed")

    def _prepull_images(self, timeout=3600):
        self.logging.info("Starting Windows images pre-pull")
        prepull_yaml_path = "/tmp/prepull-windows-images.yaml"
        e2e_utils.download_file(self.opts.prepull_yaml, prepull_yaml_path)
        e2e_utils.exec_kubectl(["apply", "-f", prepull_yaml_path])

        self.logging.info("Waiting up to %.2f minutes to pre-pull "
                          "Windows container images", timeout / 60.0)
        kwargs = {
            "stop": tenacity.stop_after_delay(timeout),  # pyright: ignore
            "wait": tenacity.wait_exponential(max=15),  # pyright: ignore
            "retry": tenacity.retry_if_exception_type(AssertionError),  # pyright: ignore # noqa:
            "reraise": True,
        }
        for attempt in tenacity.Retrying(**kwargs):
            with attempt:
                ds_yaml, _ = e2e_utils.exec_kubectl(  # pyright: ignore
                    args=["get", "-o", "yaml", "-f", prepull_yaml_path],
                    capture_output=True,
                    hide_cmd=True,
                )
                ds = yaml.safe_load(ds_yaml)  # pyright: ignore
                ready_nr = ds["status"]["numberReady"]
                desired_ready_nr = ds["status"]["desiredNumberScheduled"]
                assert ready_nr == desired_ready_nr, (
                    f"Windows images pre-pull failed: "
                    f"{ready_nr}/{desired_ready_nr} pods ready.")

        self.logging.info("Windows images successfully pre-pulled")
        self.logging.info("Cleaning up")
        e2e_utils.exec_kubectl(["delete", "--wait", "-f", prepull_yaml_path])

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
        output_file = "/tmp/conformance.yaml"
        e2e_utils.render_template("templates/conformance.yaml.j2", output_file,
                                  ctxt, self.e2e_runner_dir)
        self.k8s_client.create_from_yaml(output_file)
        self.k8s_client.wait_running_pod(self.HELPER_POD)
        self.k8s_client.wait_running_pod(self.CONFORMANCE_POD)

    def _conformance_image(self):
        tag = self.kubernetes_version.replace("+", "_")
        return f"registry.k8s.io/conformance:{tag}"

    def _conformance_tests_flags(self, num_nodes="2", node_os_distro="windows",
                                 output_dir="/output"):
        ginkgoFlags = {
            "progress": "true",
            "trace": "true",
            "v": "true",
            "nodes": self.opts.parallel_test_nodes,
            "focus": self.opts.test_focus_regex,
            "skip": self.opts.test_skip_regex,
        }
        if self.kubernetes_version > "v1.25":
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
        if os.environ.get("DOCKER_CONFIG_FILE"):
            e2eFlags["docker-config-file"] = "/docker-creds/config.json"

        return ginkgoFlags, e2eFlags
