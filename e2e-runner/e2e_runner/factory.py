from e2e_runner import base
from e2e_runner.ci.capz_flannel import capz_flannel

CI_MAP = {
    "capz_flannel": capz_flannel.CapzFlannelCI
}


def get_ci(name):
    return CI_MAP.get(name, base.CI)
