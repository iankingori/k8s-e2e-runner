import os
import subprocess

from e2e_runner import logger as e2e_logger
from e2e_runner import utils as e2e_utils


class Deployer(object):

    def __init__(self, opts):
        self.logging = e2e_logger.get_logger(__name__)
        self.opts = opts

    def up(self):
        self.logging.info("Deployer Up: NOOP")

    def down(self):
        self.logging.info("Deployer Down: NOOP")


class CI(object):

    def __init__(self, opts):
        self.logging = e2e_logger.get_logger(__name__)
        self.opts = opts
        self.e2e_runner_dir = os.path.dirname(__file__)
        self.deployer = Deployer(opts)

    def setup_bootstrap_vm(self):
        self.logging.info("CI Setup Bootstrap VM: Default NOOP")

    def cleanup_bootstrap_vm(self):
        self.logging.info("CI Cleanup Bootstrap VM: Default NOOP")

    def build(self, _):
        self.logging.info("CI Build: Default NOOP")

    def up(self):
        self.logging.info("CI Up: Default NOOP")

    def down(self):
        self.logging.info("CI Down: Default NOOP")

    def test(self):
        self._prepare_tests()
        return self._run_tests()

    @e2e_utils.retry_on_error()
    def _label_linux_nodes_no_schedule(self):
        kubectl = e2e_utils.get_kubectl_bin()
        out, _ = e2e_utils.run_shell_cmd([
            kubectl, "get", "nodes", "--selector",
            "kubernetes.io/os=linux", "--no-headers", "-o",
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

    def _prepare_tests(self):
        # - Taints linux nodes so that no pods will be scheduled there.
        # - Sets the KUBE_TEST_REPO_LIST env variable.
        # - Builds tests.
        # - Builds kubetest.
        #
        # Necessary env settings for the tests:
        # KUBE_MASTER=local
        # KUBE_MASTER_IP=dns-name-of-node
        # KUBE_MASTER_URL=https://$KUBE_MASTER_IP
        # KUBECONFIG=/path/to/kube/config
        # KUBE_TEST_REPO_LIST=/tmp/repo-list
        #
        self._label_linux_nodes_no_schedule()
        self.logging.info("Downloading repo-list")
        e2e_utils.download_file(self.opts.repo_list, "/tmp/repo-list")
        os.environ["KUBE_TEST_REPO_LIST"] = "/tmp/repo-list"
        self.logging.info("Building tests")
        e2e_utils.run_shell_cmd(
            cmd=["make", 'WHAT="test/e2e/e2e.test"'],
            cwd=e2e_utils.get_k8s_folder())
        self.logging.info("Building ginkgo")
        e2e_utils.run_shell_cmd(
            cmd=["make", 'WHAT="vendor/github.com/onsi/ginkgo/ginkgo"'],
            cwd=e2e_utils.get_k8s_folder())
        self.logging.info("Setup Kubetest")
        e2e_utils.clone_git_repo(
            "https://github.com/kubernetes/test-infra", "master",
            "/tmp/test-infra")
        e2e_utils.run_shell_cmd(
            cmd=["go", "install", "./kubetest"],
            cwd="/tmp/test-infra", env={"GO111MODULE": "on"})

    def _run_tests(self):
        # Invokes kubetest
        self.logging.info("Running tests on env.")
        test_args = (
            "--test.timeout=2h "
            "--num-nodes=2 "
            "--node-os-distro=windows "
            "--prepull-images=true "
            "--ginkgo.noColor "
            "--ginkgo.dryRun=false "
            f"--ginkgo.focus={self.opts.test_focus_regex} "
            f"--ginkgo.skip={self.opts.test_skip_regex}"
        )
        cmd = [
            "kubetest",
            "--check-version-skew=false",
            "--verbose-commands=true",
            "--provider=skeleton",
            "--test",
            f"--ginkgo-parallel={self.opts.parallel_test_nodes}",
            f"--dump={self.opts.artifacts_directory}",
            f"--test_args={test_args}",
        ]
        docker_config_file = os.environ.get("DOCKER_CONFIG_FILE")
        if docker_config_file:
            cmd.append(f" --docker-config-file={docker_config_file}")
        return subprocess.call(cmd, cwd=e2e_utils.get_k8s_folder())
