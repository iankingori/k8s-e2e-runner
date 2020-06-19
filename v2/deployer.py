import log


class NoopDeployer(object):
    def __init__(self):
        self.logging = log.getLogger(__name__)

    def up(self):
        self.logging("UP: NOOP")

    def down(self):
        self.logging("DOWN: NOOP")
