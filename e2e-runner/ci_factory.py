import ci
import terraform_flannel
import capz_flannel

CI_MAP = {
    "terraform_flannel": terraform_flannel.Terraform_Flannel,
    "capz_flannel": capz_flannel.CapzFlannelCI
}


def get_ci(name):
    ci_obj = CI_MAP.get(name, ci.CI)
    return ci_obj()
