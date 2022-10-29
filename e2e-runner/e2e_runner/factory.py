from e2e_runner import base
from e2e_runner.ci.aks import aks
from e2e_runner.ci.capz_flannel import capz_flannel

CI_MAP = {
    "capz_flannel": capz_flannel.CapzFlannelCI,
    "aks": aks.AksCI,
}


def get_ci(name):
    return CI_MAP.get(name, base.CI)
