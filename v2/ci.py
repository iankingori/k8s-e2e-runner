import deployer
import log
import utils
import os
import configargparse
import subprocess
import stat

p = configargparse.get_argument_parser()

p.add("--repo-list", default="https://raw.githubusercontent.com/kubernetes-sigs/windows-testing/master/images/image-repo-list",
                     help="Repo list with registries for test images.")
p.add("--parallel-test-nodes", default=1)
p.add("--test-dry-run", default="False")
p.add("--test-focus-regex", default="\\[Conformance\\]|\\[NodeConformance\\]|\\[sig-windows\\]")
p.add("--test-skip-regex", default="\\[LinuxOnly\\]")
p.add("--kubetest-link", default="")

class CI(object):

    def __init__(self):
        self.opts = p.parse_known_args()[0]
        self.logging = log.getLogger(__name__)
        self.deployer = deployer.NoopDeployer()

    def up(self):
        #pass
        self.logging.info("UP: Default NOOP")

    def build(self):
        self.logging.info("BUILD: Default NOOP")

    def down(self):
       #pass
        self.logging.info("DOWN: Default NOOP")

    def _prepareTestEnv(self):
        # Should be implemented by each CI type
        # sets environment variables and other settings and copies over kubeconfig
        # Necessary env settings:
        # Repo list will be downloaded in _prepareTests() as that would be less likely to be reimplemented
        # Necessary env vars:
        # KUBE_MASTER=local
        # KUBE_MASTER_IP=dns-name-of-node
        # KUBE_MASTER_URL=https://$KUBE_MASTER_IP
        # KUBECONFIG=/path/to/kube/config
        # KUBE_TEST_REPO_LIST= will be set in _prepareTests
        #pass
        self.logging.info("PREPARE TEST ENV: Default NOOP")

    def _getKubetest(self):
        self.logging.info("Get Kubetest")
        if self.opts.kubetest_link == "":
            os.putenv("GO111MODULE", "on")
            cmd = ["go", "get", "k8s.io/test-infra/kubetest"]
            _, err, ret = utils.run_cmd(cmd, stderr=True)
            if ret != 0:
                self.logging.error("Failed to get kubetest binary with error: %s" % err)
                raise Exception("Failed to get kubetest binary with errorr: %s" % err)
        else:
            kubetestbin = "/usr/bin/kubetest"
            utils.download_file(self.opts.kubetest_link, kubetestbin)
            os.chmod(kubetestbin, stat.S_IRWXU | stat.S_IRWXG)

    def _prepareTests(self):
        # Sets KUBE_TEST_REPO_LIST
        # Builds tests
        # Taints linux nodes so that no pods will be scheduled there.
        kubectl = os.environ.get("KUBECTL_PATH") if os.environ.get("KUBECTL_PATH") else os.path.join(utils.get_k8s_folder(), "cluster/kubectl.sh")
        cmd = [kubectl, "get", "nodes","--selector","beta.kubernetes.io/os=linux","--no-headers", "-o", "custom-columns=NAME:.metadata.name"]

        out, err, ret = utils.run_cmd(cmd, stdout=True, stderr=True)
        if ret != 0:
            self.logging.info("Failed to get kubernetes nodes: %s." % err)
            raise Exception("Failed to get kubernetes nodes: %s." % err)
        linux_nodes = out.strip().split("\n")
        for node in linux_nodes:
            taint_cmd=[kubectl, "taint", "nodes", node, "node-role.kubernetes.io/master=:NoSchedule"]
            label_cmd=[kubectl, "label", "nodes", node, "node-role.kubernetes.io/master=NoSchedule"]
            _, err, ret = utils.run_cmd(taint_cmd, stderr=True)
            if ret != 0:
                self.logging.info("Failed to taint node %s with error %s." %(node, err))
                raise Exception("Failed to taint node %s with error %s." %(node, err))
            _, err, ret = utils.run_cmd(label_cmd, stderr=True)
            if ret != 0:
                self.logging.info("Failed to label node %s with error %s." %(node, err))
                raise Exception("Failed to label node %s with error %s." %(node, err))


        self.logging.info("Downloading repo-list.")
        utils.download_file(self.opts.repo_list, "/tmp/repo-list")
        os.environ["KUBE_TEST_REPO_LIST"] = "/tmp/repo-list"

        self.logging.info("Building tests.")
        cmd = ["make", 'WHAT="test/e2e/e2e.test"']
        _, err, ret = utils.run_cmd(cmd, stderr=True, cwd=utils.get_k8s_folder())

        if ret != 0:
            self.logging.error("Failed to build k8s test binaries with error: %s" % err)
            raise Exception("Failed to build k8s test binaries with error: %s" % err)

        self.logging.info("Building ginkgo")
        cmd = ["make", 'WHAT="vendor/github.com/onsi/ginkgo/ginkgo"']
        _, err, ret = utils.run_cmd(cmd, stderr=True, cwd=utils.get_k8s_folder())

        if ret != 0:
            self.logging.error("Failed to build k8s ginkgo binaries with error: %s" % err)
            raise Exception("Failed to build k8s ginkgo binaries with error: %s" % err)

        self._getKubetest()

    def _runTests(self):
        # invokes kubetest
        self.logging.info("Running tests on env.")
        cmd = ["kubetest"]
        cmd.append("--ginkgo-parallel=%s" % self.opts.parallel_test_nodes)
        cmd.append("--verbose-commands=true")
        cmd.append("--provider=skeleton")
        cmd.append("--test")
        cmd.append("--dump=%s" % self.opts.log_path)
        cmd.append('--test_args=--ginkgo.flakeAttempts=1 --num-nodes=2 --ginkgo.noColor --ginkgo.dryRun=%(dryRun)s --node-os-distro=windows --ginkgo.focus=%(focus)s --ginkgo.skip=%(skip)s' % {
                                                                                                "dryRun": self.opts.test_dry_run,
                                                                                                "focus": self.opts.test_focus_regex,
                                                                                                "skip": self.opts.test_skip_regex
                                                                                             })
        return subprocess.call(cmd, cwd=utils.get_k8s_folder())

    def test(self):
        self._prepareTestEnv()
        self._prepareTests()
        # Only for debugging in a container. Will speep so user can run tests on a prepared env.
        if self.opts.hold == True:
            import time
            time.sleep(1000000)
        ret = self._runTests()
        return ret
