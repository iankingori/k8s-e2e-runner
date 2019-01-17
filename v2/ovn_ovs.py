import ci
import configargparse
import openstack_wrap as openstack
import logging
import utils
import os
import shutil
import constants

p = configargparse.get_argument_parser()

p.add("--linuxVMs", action="append", help="Name for linux VMS. List.")
p.add("--linuxUserData", help="Linux VMS user-data.")
p.add("--linuxFlavor", help="Linux VM flavor.")
p.add("--linuxImageID", help="ImageID for linux VMs.")

p.add("--windowsVMs", action="append", help="Name for Windows VMs. List.")
p.add("--windowsUserData", help="Windows VMS user-data.")
p.add("--windowsFlavor", help="Windows VM flavor.")
p.add("--windowsImageID", help="ImageID for windows VMs.")

p.add("--keyName", help="Openstack SSH key name")
p.add("--keyFile", help="Openstack SSH private key")

p.add("--internalNet", help="Internal Network for VMs")
p.add("--externalNet", help="External Network for floating ips")

p.add("--ansibleRepo", default="http://github.com/openvswitch/ovn-kubernetes", help="Ansible Repository for ovn-ovs playbooks.")
p.add("--ansibleBranch", default="master", help="Ansible Repository branch for ovn-ovs playbooks.")

class OVN_OVS_CI(ci.CI):

    DEFAULT_ANSIBLE_PATH="/tmp/ovn-kubernetes"
    ANSIBLE_PLAYBOOK="ovn-kubernetes-cluster.yaml"
    ANSIBLE_CONTRIB_PATH="%s/contrib" % DEFAULT_ANSIBLE_PATH
    ANSIBLE_HOSTS_TEMPLATE=("[kube-master]\nKUBE_MASTER_PLACEHOLDER\n\n[kube-minions-linux]\nKUBE_MINIONS_LINUX_PLACEHOLDER\n\n"
                            "[kube-minions-windows]\nKUBE_MINIONS_WINDOWS_PLACEHOLDER\n")
    ANSIBLE_HOSTS_PATH="%s/contrib/inventory/hosts" % DEFAULT_ANSIBLE_PATH
    DEFAULT_ANSIBLE_WINDOWS_ADMIN="Admin"
    DEFAULT_ANSIBLE_HOST_VAR_WINDOWS_TEMPLATE="ansible_user: USERNAME_PLACEHOLDER\nansible_password: PASS_PLACEHOLDER\n"
    DEFAULT_ANSIBLE_HOST_VAR_DIR="%s/contrib/inventory/host_vars" % DEFAULT_ANSIBLE_PATH
    HOSTS_FILE="/etc/hosts"
    ANSIBLE_CONFIG_FILE="%s/contrib/ansible.cfg" % DEFAULT_ANSIBLE_PATH

    def __init__(self):
        self.opts = p.parse_known_args()[0]
        self.cluster = {}

    def _add_linux_vm(self, vm_obj):
        if self.cluster.get("linuxVMs") == None:
            self.cluster["linuxVMs"] = []
        self.cluster["linuxVMs"].append(vm_obj)

    def _add_windows_vm(self, vm_obj):
        if self.cluster.get("windowsVMs") == None:
            self.cluster["windowsVMs"] = []
        self.cluster["windowsVMs"].append(vm_obj)

    def _get_windows_vms(self):
        return self.cluster.get("windowsVMs")

    def _get_linux_vms(self):
        return self.cluster.get("linuxVMs")

    def _get_all_vms(self):
        return self._get_linux_vms() + self._get_windows_vms()

    def _get_vm_fip(self, vm_obj):
        return vm_obj.get("FloatingIP")

    def _set_vm_fip(self, vm_obj, ip):
        vm_obj["FloatingIP"] = ip 

    def _create_vms(self):
        logging.info("Creating Openstack VMs")
        vmPrefix = self.opts.cluster_name
        for vm in self.opts.linuxVMs:
            openstack_vm = openstack.server_create("%s-%s" % (vmPrefix, vm), self.opts.linuxFlavor, self.opts.linuxImageID, 
                                                   self.opts.internalNet, self.opts.keyName, self.opts.linuxUserData)
            fip = openstack.get_floating_ip(openstack.floating_ip_list()[0])
            openstack.server_add_floating_ip(openstack_vm['name'], fip)
            self._set_vm_fip(openstack_vm, fip)
            self._add_linux_vm(openstack_vm)
        for vm in self.opts.windowsVMs:
            openstack_vm = openstack.server_create("%s-%s" % (vmPrefix, vm), self.opts.windowsFlavor, self.opts.windowsImageID, 
                                                   self.opts.internalNet, self.opts.keyName, self.opts.windowsUserData)
            fip = openstack.get_floating_ip(openstack.floating_ip_list()[0])
            openstack.server_add_floating_ip(openstack_vm['name'], fip)
            self._set_vm_fip(openstack_vm, fip)
            self._add_windows_vm(openstack_vm)
        logging.info("Succesfuly created VMs %s" % [ vm.get("name") for vm in self._get_all_vms()])

    def _wait_for_windows_machines(self):
        logging.info("Waiting for Windows VMs to obtain Admin password.")
        for vm in self._get_windows_vms():
            openstack.server_get_password(vm['name'], self.opts.keyFile)
            logging.info("Windows VM: %s succesfully obtained password." % vm.get("name"))

    def _prepare_env(self):
        self._create_vms()
        self._wait_for_windows_machines()

    def _destroy_cluster(self):
        vmPrefix = self.opts.cluster_name
        for vm in self.opts.linuxVMs:
            openstack.server_delete("%s-%s" % (vmPrefix, vm))
        for vm in self.opts.windowsVMs:
            openstack.server_delete("%s-%s" % (vmPrefix, vm))

    def _prepare_ansible(self):
        utils.clone_repo(self.opts.ansibleRepo, self.opts.ansibleBranch, OVN_OVS_CI.DEFAULT_ANSIBLE_PATH)
        
        # Creating ansible hosts file
        linux_master = self._get_linux_vms()[0].get("name")
        linux_minions = [vm.get("name") for vm in self._get_linux_vms()[1:]]
        windows_minions = [vm.get("name") for vm in self._get_windows_vms()]

        hosts_file_content = OVN_OVS_CI.ANSIBLE_HOSTS_TEMPLATE.replace("KUBE_MASTER_PLACEHOLDER", linux_master)
        hosts_file_content = hosts_file_content.replace("KUBE_MINIONS_LINUX_PLACEHOLDER", "\n".join(linux_minions))
        hosts_file_content = hosts_file_content.replace("KUBE_MINIONS_WINDOWS_PLACEHOLDER","\n".join(windows_minions))

        logging.info("Writing hosts file for ansible inventory.")
        with open(OVN_OVS_CI.ANSIBLE_HOSTS_PATH, "w") as f:
            f.write(hosts_file_content)

        # Creating hosts_vars for hosts
        for vm in self._get_windows_vms():
            vm_name = vm.get("name")
            vm_username = OVN_OVS_CI.DEFAULT_ANSIBLE_WINDOWS_ADMIN # TO DO: Have this configurable trough opts
            vm_pass = openstack.server_get_password(vm_name, self.opts.keyFile)
            hosts_var_content = OVN_OVS_CI.DEFAULT_ANSIBLE_HOST_VAR_WINDOWS_TEMPLATE.replace("USERNAME_PLACEHOLDER", vm_username).replace("PASS_PLACEHOLDER", vm_pass)
            filepath = os.path.join(OVN_OVS_CI.DEFAULT_ANSIBLE_HOST_VAR_DIR, vm_name)
            with open(filepath, "w") as f:
                f.write(hosts_var_content)

        # Populate hosts file
        with open(OVN_OVS_CI.HOSTS_FILE,"a") as f:
            for vm in self._get_all_vms():
                hosts_entry=("%s %s\n" % (self._get_vm_fip(vm), vm.get("name")))
                logging.info("Adding entry %s to hosts file." % hosts_entry)
                f.write(hosts_entry)

        # Enable ansible log and set ssh options
        with open(OVN_OVS_CI.ANSIBLE_CONFIG_FILE, "a") as f:
            log_file = os.path.join(self.opts.log_path, "ansible-deploy.log")
            log_config = "log_path=%s\n" % log_file
            # This probably goes better in /etc/ansible.cfg (set in dockerfile )
            ansible_config="\n\n[ssh_connection]\nssh_args=-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null\n"
            f.write(log_config) 
            f.write(ansible_config)

        full_ansible_tmp_path = os.path.join(OVN_OVS_CI.ANSIBLE_CONTRIB_PATH, "tmp")
        utils.mkdir_p(full_ansible_tmp_path)
        # Copy kubernetes prebuilt binaries
        for file in ["kubelet","kubectl","kube-apiserver","kube-controller-manager","kube-scheduler"]:
            full_file_path = os.path.join(utils.get_k8s_folder(), constants.KUBERNETES_LINUX_BINS_LOCATION, file)
            logging.info("Copying %s to %s." % (full_file_path, full_ansible_tmp_path))
            shutil.copy(full_file_path, full_ansible_tmp_path)

        for file in ["kubelet.exe", "kubectl.exe"]:
            full_file_path = os.path.join(utils.get_k8s_folder(), constants.KUBERNETES_WINDOWS_BINS_LOCATION, file)
            logging.info("Copying %s to %s." % (full_file_path, full_ansible_tmp_path))
            shutil.copy(full_file_path, full_ansible_tmp_path)

    def _deploy_ansible(self):
        logging.info("Starting Ansible deployment.")
        cmd = "ansible-playbook ovn-kubernetes-cluster.yml -v"
        cmd = cmd.split()
        cmd.append("--key-file=%s" % self.opts.keyFile)

        _, err ,ret = utils.run_cmd(cmd, stderr=True, cwd=OVN_OVS_CI.ANSIBLE_CONTRIB_PATH)

        if ret != 0:
            logging.error("Failed to deploy ansible-playbook with error: %s" % err)
            raise Exception("Failed to deploy ansible-playbook with error: %s" % err)
        logging.info("Succesfully deployed ansible-playbook.")
        
        
    def up(self):
        logging.info("OVN-OVS: Bringing cluster up.")
        try:
            self._prepare_env()
            self._prepare_ansible()
            self._deploy_ansible()
        except Exception as e:
            raise e
    
    def down(self):
        logging.info("OVN-OVS: Destroying cluster.")
        try:
            self._destroy_cluster()
        except Exception as e:
            raise e