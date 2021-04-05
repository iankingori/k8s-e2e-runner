import os

from cliff.command import Command

from e2e_runner import (
    constants,
    factory,
    logger,
    utils
)


class RunCI(Command):
    """Run the E2E Runner CI"""

    logging = logger.get_logger(__name__)

    def get_parser(self, prog_name):
        p = super(RunCI, self).get_parser(prog_name)

        p.add_argument('--artifacts-directory', default='/tmp/ci_artifacts',
                       help='Local path to place all the artifacts.')
        p.add_argument('--install-patch', action='append', default=[],
                       help='URLs of KBs to install on Windows nodes.')
        p.add_argument('--up', type=utils.str2bool, default=False,
                       help='Deploy test cluster.')
        p.add_argument('--down', type=utils.str2bool, default=False,
                       help='Destroy cluster on finish.')
        p.add_argument('--build', action='append', default=[],
                       choices=['k8sbins', 'containerdbins',
                                'containerdshim', 'sdncnibins'],
                       help='Binaries to build.')
        p.add_argument('--test', type=utils.str2bool, default=False,
                       help='Whether to run tests.')

        p.add_argument("--repo-list",
                       default="https://raw.githubusercontent.com/"
                       "kubernetes-sigs/windows-testing/"
                       "master/images/image-repo-list",
                       help="Repo list with registries for test images.")
        p.add_argument("--parallel-test-nodes", default=1)
        p.add_argument("--test-dry-run", type=utils.str2bool, default=False)
        p.add_argument("--test-focus-regex", default="\\[Conformance\\]|"
                       "\\[NodeConformance\\]|\\[sig-windows\\]")
        p.add_argument("--test-skip-regex", default="\\[LinuxOnly\\]")
        p.add_argument("--kubetest-link",
                       help="Download link for a kubetest binary.")
        p.add_argument("--prepull-yaml",
                       default="https://raw.githubusercontent.com/"
                       "kubernetes-sigs/windows-testing/"
                       "master/gce/prepull.yaml",
                       help="Download link for the manifest file used to "
                       "pre-pull the container images on the nodes.")
        p.add_argument("--hold", choices=["before", "after"],
                       help="Useful for debugging. Sleeps the process either "
                       "right before or right after running the tests.")

        p.add_argument('--k8s-repo',
                       default='https://github.com/kubernetes/kubernetes')
        p.add_argument('--k8s-branch',
                       default=constants.DEFAULT_KUBERNETES_VERSION)

        p.add_argument('--containerd-repo',
                       default='https://github.com/containerd/containerd')
        p.add_argument('--containerd-branch', default='master')

        p.add_argument('--containerd-shim-repo',
                       default='https://github.com/microsoft/hcsshim')
        p.add_argument('--containerd-shim-branch', default='master')

        p.add_argument('--sdn-repo', default='https://github.com/'
                       'microsoft/windows-container-networking')
        p.add_argument('--sdn-branch', default='master')

        p.add_argument("--cri-tools-repo",
                       default="https://github.com/kubernetes-sigs/cri-tools",
                       help="The cri-tools repository. It is used to build "
                       "the crictl tool.")
        p.add_argument("--cri-tools-branch", default="master",
                       help="The cri-tools branch.")

        subparsers = p.add_subparsers(dest='ci', help='The CI type.')
        self.add_capz_flannel_subparser(subparsers)

        return p

    def add_capz_flannel_subparser(self, subparsers):
        p = subparsers.add_parser('capz_flannel')
        p.add_argument("--container-runtime", default="docker",
                       choices=["docker", "containerd"],
                       help="Container runtime used by the Kubernetes agents.")
        p.add_argument("--flannel-mode",
                       default=constants.FLANNEL_MODE_OVERLAY,
                       choices=[constants.FLANNEL_MODE_OVERLAY,
                                constants.FLANNEL_MODE_L2BRIDGE],
                       help="Flannel mode used by the CI.")
        p.add_argument("--base-container-image-tag", default="ltsc2019",
                       choices=["ltsc2019", "1909", "2004"],
                       help="The base container image used for the "
                       "kube-proxy / flannel CNI. This needs to be adjusted "
                       "depending on the Windows minion Azure image.")
        p.add_argument("--kubernetes-version",
                       default=constants.DEFAULT_KUBERNETES_VERSION,
                       help="The Kubernetes version to deploy. If "
                       "'--build=k8sbins' is specified, this parameter is "
                       "overwriten by the version of the newly built k8s "
                       "binaries")
        p.add_argument('--enable-win-dsr', type=utils.str2bool, default=False)
        p.add_argument('--enable-ipv6dualstack',
                       type=utils.str2bool, default=False,
                       help='Enables the IPv6DualStack feature gate for '
                       'kubelet and kube-proxy.')
        p.add_argument("--cluster-name", required=True,
                       help="The cluster name given to the cluster-api "
                       "manifest. This value is used for the Azure resource "
                       "group name as well.")
        p.add_argument("--cluster-network-subnet", default="10.244.0.0/16",
                       help="The cluster network subnet given to the "
                       "cluster-api manifest")
        p.add_argument("--location",
                       help="The Azure location for the spawned resource.")
        p.add_argument("--vnet-cidr-block", default="10.0.0.0/8",
                       help="The vNET CIDR block.")
        p.add_argument("--control-plane-subnet-cidr-block",
                       default="10.0.0.0/16",
                       help="The control plane subnet CIDR block.")
        p.add_argument("--node-subnet-cidr-block", default="10.1.0.0/16",
                       help="The node subnet CIDR block.")
        p.add_argument("--bootstrap-vm-size", default="Standard_D2s_v3",
                       help="Size of the bootstrap VM")
        p.add_argument("--master-vm-size", default="Standard_D2s_v3",
                       help="Size of master virtual machine.")
        p.add_argument("--win-minion-count", type=int, default=2,
                       help="Number of Windows minions for the deployment.")
        p.add_argument("--win-minion-size", default="Standard_D2s_v3",
                       help="Size of Windows minions.")
        p.add_argument("--win-minion-image-type", type=str,
                       default=constants.SHARED_IMAGE_GALLERY_TYPE,
                       choices=[constants.SHARED_IMAGE_GALLERY_TYPE,
                                constants.MANAGED_IMAGE_TYPE],
                       help="The type of image used to provision Windows "
                       "agents.")
        p.add_argument("--win-minion-image-id",
                       help="The Azure managed image to be used for the "
                       "Windows agents.")
        p.add_argument("--win-minion-gallery-image",
                       help="The Windows minion shared gallery. The "
                       "parameter shall be given as: "
                       "<IMG_GALLERY_RG>:<IMG_GALLERY_NAME>:"
                       "<IMG_DEFINITION>:<IMG_VERSION>")

    def take_action(self, args):
        self.logging.info("Starting with CI: %s.", args.ci)
        self.logging.info("Creating artifacts dir: %s.",
                          args.artifacts_directory)
        os.makedirs(args.artifacts_directory, exist_ok=True)
        ci = factory.get_ci(args.ci)(args)

        try:
            ci.build(args.build)
            ci.set_patches(args.install_patch)

            if args.up is True:
                ci.up()
            else:
                ci.reclaim()

            if args.test is True:
                success = ci.test()
                if success != 0:
                    raise Exception("CI Tests failed")

        except Exception as e:
            self.logging.error("{}".format(e))
            raise e

        finally:
            ci.collectWindowsLogs()
            ci.collectLinuxLogs()
            if args.down is True:
                ci.down()
