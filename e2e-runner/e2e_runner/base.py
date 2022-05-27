import os

from e2e_runner import logger as e2e_logger


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
        self.logging.info("CI Test: Default NOOP")
