import ci
import time
import log


class Flannel_CI(ci.CI):

    DEFAULT_ANSIBLE_PATH = "/tmp/flannel-kubernetes"
    ANSIBLE_PLAYBOOK = "kubernetes-cluster.yml"
    ANSIBLE_PLAYBOOK_ROOT = DEFAULT_ANSIBLE_PATH
    ANSIBLE_HOSTS_TEMPLATE = ("[kube-master]\nKUBE_MASTER_PLACEHOLDER\n\n[kube-minions-linux]\nKUBE_MINIONS_LINUX_PLACEHOLDER\n\n"
                              "[kube-minions-windows]\nKUBE_MINIONS_WINDOWS_PLACEHOLDER\n")
    ANSIBLE_HOSTS_PATH = "%s/inventory/hosts" % ANSIBLE_PLAYBOOK_ROOT
    DEFAULT_ANSIBLE_WINDOWS_ADMIN = "Admin"
    DEFAULT_ANSIBLE_HOST_VAR_WINDOWS_TEMPLATE = "ansible_user: USERNAME_PLACEHOLDER\nansible_password: PASS_PLACEHOLDER\n"
    DEFAULT_ANSIBLE_HOST_VAR_DIR = "%s/inventory/host_vars" % ANSIBLE_PLAYBOOK_ROOT
    HOSTS_FILE = "/etc/hosts"
    ANSIBLE_CONFIG_FILE = "%s/ansible.cfg" % ANSIBLE_PLAYBOOK_ROOT

    KUBE_CONFIG_PATH = "/root/.kube/config"
    KUBE_TLS_SRC_PATH = "/etc/kubernetes/tls/"

    def __init__(self):
        super(Flannel_CI, self).__init__()
        self.default_ansible_path = Flannel_CI.DEFAULT_ANSIBLE_PATH
        self.ansible_playbook = Flannel_CI.ANSIBLE_PLAYBOOK
        self.ansible_playbook_root = Flannel_CI.ANSIBLE_PLAYBOOK_ROOT
        self.ansible_hosts_template = Flannel_CI.ANSIBLE_HOSTS_TEMPLATE
        self.ansible_hosts_path = Flannel_CI.ANSIBLE_HOSTS_PATH
        self.ansible_windows_admin = Flannel_CI.DEFAULT_ANSIBLE_WINDOWS_ADMIN
        self.ansible_host_var_windows_template = Flannel_CI.DEFAULT_ANSIBLE_HOST_VAR_WINDOWS_TEMPLATE
        self.ansible_host_var_dir = Flannel_CI.DEFAULT_ANSIBLE_HOST_VAR_DIR
        self.ansible_config_file = Flannel_CI.ANSIBLE_CONFIG_FILE
        self.logging = log.getLogger(__name__)

        self.post_deploy_reboot_required = False
