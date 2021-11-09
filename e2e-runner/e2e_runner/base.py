import os
import subprocess
import stat
import time
import urllib

from e2e_runner import (
    logger,
    utils,
)


class Deployer(object):

    def __init__(self):
        self.logging = logger.get_logger(__name__)

    def up(self):
        self.logging("UP: NOOP")

    def down(self):
        self.logging("DOWN: NOOP")


class CI(object):

    def __init__(self, opts):
        self.logging = logger.get_logger(__name__)
        self.opts = opts
        self.e2e_runner_dir = os.path.dirname(__file__)
        self.deployer = Deployer()

    def setup_infra(self):
        self.logging.info("Setup Infra: Default NOOP")

    def up(self):
        self.logging.info("UP: Default NOOP")

    def reclaim(self):
        self.logging.info("RECLAIM: Default NOOP")

    def build(self, bins_to_build):
        self.logging.info("BUILD %s: Default NOOP", bins_to_build)

    def down(self):
        self.logging.info("DOWN: Default NOOP")

    def _prepare_test_env(self):
        # Should be implemented by each CI type sets environment variables
        # and other settings and copies over kubeconfig. Repo list will be
        # downloaded in _prepare_tests() as that would be less likely to be
        # reimplemented.
        #
        # Necessary env settings:
        # KUBE_MASTER=local
        # KUBE_MASTER_IP=dns-name-of-node
        # KUBE_MASTER_URL=https://$KUBE_MASTER_IP
        # KUBECONFIG=/path/to/kube/config
        # KUBE_TEST_REPO_LIST= will be set in _prepare_tests
        self.logging.info("PREPARE TEST ENV: Default NOOP")

    def _setup_kubetest(self):
        self.logging.info("Setup Kubetest")
        if self.opts.kubetest_link:
            kubetestbin = "/usr/bin/kubetest"
            urllib.request.urlretrieve(self.opts.kubetest_link, kubetestbin)
            os.chmod(kubetestbin, stat.S_IRWXU | stat.S_IRWXG)
            return
        # Clone repository using git and then install. Workaround for:
        # https://github.com/kubernetes/test-infra/issues/14712
        utils.clone_git_repo(
            "https://github.com/kubernetes/test-infra", "master",
            "/tmp/test-infra")
        utils.run_shell_cmd(
            cmd=["go", "install", "./kubetest"],
            cwd="/tmp/test-infra", env={"GO111MODULE": "on"})

    def _prepare_tests(self):
        # Sets KUBE_TEST_REPO_LIST
        # Builds tests
        # Taints linux nodes so that no pods will be scheduled there.
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
        urllib.request.urlretrieve(self.opts.repo_list, "/tmp/repo-list")
        os.environ["KUBE_TEST_REPO_LIST"] = "/tmp/repo-list"
        self.logging.info("Building tests")
        utils.run_shell_cmd(
            cmd=["make", 'WHAT="test/e2e/e2e.test"'],
            cwd=utils.get_k8s_folder())
        self.logging.info("Building ginkgo")
        utils.run_shell_cmd(
            cmd=["make", 'WHAT="vendor/github.com/onsi/ginkgo/ginkgo"'],
            cwd=utils.get_k8s_folder())
        self._setup_kubetest()

    def _run_tests(self):
        # Invokes kubetest
        self.logging.info("Running tests on env.")
        cmd = ["kubetest"]
        cmd.append("--check-version-skew=false")
        cmd.append("--ginkgo-parallel=%s" % self.opts.parallel_test_nodes)
        cmd.append("--verbose-commands=true")
        cmd.append("--provider=skeleton")
        cmd.append("--test")
        cmd.append("--dump=%s" % self.opts.artifacts_directory)
        cmd.append(
            ('--test_args=--ginkgo.flakeAttempts=1 '
             '--test.timeout=2h '
             '--num-nodes=2 --ginkgo.noColor '
             '--ginkgo.dryRun=%(dryRun)s '
             '--node-os-distro=windows '
             '--ginkgo.focus=%(focus)s '
             '--ginkgo.skip=%(skip)s') % {
                 "dryRun": self.opts.test_dry_run,
                 "focus": self.opts.test_focus_regex,
                 "skip": self.opts.test_skip_regex})
        docker_config_file = os.environ.get("DOCKER_CONFIG_FILE")
        if docker_config_file:
            cmd.append(' --docker-config-file=%s' % docker_config_file)
        return subprocess.call(cmd, cwd=utils.get_k8s_folder())

    def test(self):
        self._prepare_test_env()
        self._prepare_tests()
        # Hold before tests
        if self.opts.hold == "before":
            self.logging.info("Holding before tests...")
            time.sleep(1000000)
        ret = self._run_tests()
        # Hold after tests
        if self.opts.hold == "after":
            self.logging.info("Holding after tests...")
            time.sleep(1000000)
        return ret
