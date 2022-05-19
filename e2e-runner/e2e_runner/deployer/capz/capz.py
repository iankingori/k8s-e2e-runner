import base64
import os
import random
import shutil
import yaml

import tenacity

from pathlib import Path
from urllib.parse import urlparse

from azure.core import exceptions as azure_exceptions
from azure.identity import ClientSecretCredential

from azure.mgmt.network import models as net_models
from azure.mgmt.compute import models as compute_models
from azure.mgmt.resource.resources import models as res_models

from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.compute import ComputeManagementClient

from e2e_runner import base as e2e_base
from e2e_runner import logger as e2e_logger
from e2e_runner import constants as e2e_constants
from e2e_runner import exceptions as e2e_exceptions
from e2e_runner import utils as e2e_utils


class CAPZProvisioner(e2e_base.Deployer):

    def __init__(self, opts, resource_group_tags={}):
        super(CAPZProvisioner, self).__init__(opts)

        self.e2e_runner_dir = str(Path(__file__).parents[2])
        self.capz_dir = os.path.dirname(__file__)
        self.logging = e2e_logger.get_logger(__name__)

        self.resource_group_tags = resource_group_tags
        self.kubectl = e2e_utils.get_kubectl_bin()
        self.bins_built = []
        self.kubernetes_version = self.opts.kubernetes_version
        self.mgmt_kubeconfig_path = "/tmp/mgmt-kubeconfig.yaml"
        self.capz_kubeconfig_path = "/tmp/capz-kubeconfig.yaml"

        self.bootstrap_vm = None
        self.bootstrap_vm_rg_name = f"{self.opts.cluster_name}-bootstrap"
        self.bootstrap_vm_vnet_name = "k8s-bootstrap-vnet"
        self.bootstrap_vm_vnet_cidr_block = "192.168.0.0/16"
        self.bootstrap_vm_subnet_name = "k8s-bootstrap-subnet"
        self.bootstrap_vm_subnet_cidr = "192.168.0.0/24"
        self.bootstrap_vm_nsg_name = "k8s-bootstrap-nsg"
        self.bootstrap_vm_name = "k8s-bootstrap"
        self.bootstrap_vm_nic_name = "k8s-bootstrap-nic"
        self.bootstrap_vm_public_ip_name = "k8s-bootstrap-public-ip"
        self.bootstrap_vm_size = self.opts.bootstrap_vm_size
        self.bootstrap_vm_logs_dir = os.path.join(
            self.opts.artifacts_directory, "bootstrap_vm_logs")

        self._set_azure_variables()
        credentials, subscription_id = self._get_azure_credentials()
        self.resource_mgmt_client = ResourceManagementClient(
            credentials, subscription_id)
        self.network_client = NetworkManagementClient(
            credentials, subscription_id)
        self.compute_client = ComputeManagementClient(
            credentials, subscription_id)

    @property
    def master_public_address(self):
        if os.path.exists(self.capz_kubeconfig_path):
            master_address, _ = self._parse_capz_kubeconfig()
            return master_address
        if self.bootstrap_vm:
            column = "MASTER_ADDRESS:.spec.controlPlaneEndpoint.host"
            output, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
                self.kubectl, "get", "cluster", "--kubeconfig",
                self.mgmt_kubeconfig_path, self.opts.cluster_name,
                "-o", f"custom-columns={column}",  "--no-headers"
            ])
            return output.decode().strip()
        raise Exception("Could not find K8s master address")

    @property
    def master_public_port(self):
        if os.path.exists(self.capz_kubeconfig_path):
            _, master_port = self._parse_capz_kubeconfig()
            return master_port
        if self.bootstrap_vm:
            output, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
                self.kubectl, "get", "cluster", "--kubeconfig",
                self.mgmt_kubeconfig_path, self.opts.cluster_name, "-o",
                "custom-columns=MASTER_PORT:.spec.controlPlaneEndpoint.port",
                "--no-headers"
            ])
            return int(output.decode().strip())
        raise Exception("Could not find K8s master port")

    @property
    def linux_private_addresses(self):
        return self._get_agents_private_addresses("linux")

    @property
    def windows_private_addresses(self):
        return self._get_agents_private_addresses("windows")

    @property
    def remote_go_path(self):
        return "~/go"

    @property
    def remote_k8s_path(self):
        return os.path.join(self.remote_go_path, "src/k8s.io/kubernetes")

    @property
    def remote_containerd_path(self):
        return os.path.join(self.remote_go_path,
                            "src", "github.com", "containerd", "containerd")

    @property
    def remote_artifacts_dir(self):
        return "~/www"

    @property
    def remote_sdn_path(self):
        return os.path.join(self.remote_go_path,
                            "src", "github.com",
                            "Microsoft", "windows-container-networking")

    @property
    def remote_test_infra_path(self):
        return os.path.join(self.remote_go_path,
                            "src", "github.com", "kubernetes", "test-infra")

    @property
    def remote_containerd_shim_path(self):
        return os.path.join(self.remote_go_path,
                            "src", "github.com", "Microsoft", "hcsshim")

    @property
    def bootstrap_vm_private_ip(self):
        return self.bootstrap_vm['private_ip']

    @property
    def bootstrap_vm_public_ip(self):
        return self.bootstrap_vm['public_ip']

    @property
    def k8s_image_version(self):
        if "k8sbins" in self.bins_built:
            return e2e_constants.DEFAULT_KUBERNETES_VERSION
        return self.kubernetes_version

    def up(self):
        self._setup_capz_components()
        self._create_capz_cluster()
        self._wait_capz_control_plane()
        self._setup_capz_kubeconfig()

    def down(self):
        self.logging.info("Deleting bootstrap resource group")
        self._delete_resource_group(self.bootstrap_vm_rg_name, wait=False)
        self.logging.info("Deleting CAPZ cluster resource group")
        self._delete_resource_group(self.opts.cluster_name, wait=False)

    @e2e_utils.retry_on_error()
    def setup_bootstrap_vm(self):
        self.logging.info("Setting up the bootstrap VM")
        try:
            self._create_bootstrap_resource_group()
            self._create_bootstrap_vnet()
            self._create_bootstrap_subnet()
            self.bootstrap_vm = self._create_bootstrap_azure_vm()
            self._init_bootstrap_vm()
            self._setup_mgmt_kubeconfig()
        except Exception as ex:
            self._delete_resource_group(self.bootstrap_vm_rg_name, wait=True)
            raise ex

    def cleanup_bootstrap_vm(self):
        self.collect_bootstrap_vm_logs()
        self.logging.info("Cleaning up the bootstrap VM")
        self.logging.info("Deleting bootstrap VM resource group")
        self._delete_resource_group(self.bootstrap_vm_rg_name, wait=False)
        self.bootstrap_vm = None

    @e2e_utils.retry_on_error()
    def upload_to_bootstrap_vm(self, local_path, remote_path):
        e2e_utils.rsync_upload(
            local_path=local_path, remote_path=remote_path,
            ssh_user="capi", ssh_address=self.bootstrap_vm_public_ip,
            ssh_key_path=os.environ["SSH_KEY"])

    @e2e_utils.retry_on_error()
    def download_from_bootstrap_vm(self, remote_path, local_path):
        e2e_utils.rsync_download(
            remote_path=remote_path, local_path=local_path,
            ssh_user="capi", ssh_address=self.bootstrap_vm_public_ip,
            ssh_key_path=os.environ["SSH_KEY"])

    @e2e_utils.retry_on_error()
    def run_cmd_on_bootstrap_vm(self, cmd, timeout=3600, cwd="~",
                                return_result=False):
        return e2e_utils.run_remote_ssh_cmd(
            cmd=cmd, ssh_user="capi", ssh_address=self.bootstrap_vm_public_ip,
            ssh_key_path=os.environ["SSH_KEY"], cwd=cwd, timeout=timeout,
            return_result=return_result)

    def remote_clone_git_repo(self, repo_url, branch_name, remote_dir):
        clone_cmd = (
            f"test -e {remote_dir} || "
            f"git clone --single-branch "
            f"{repo_url} --branch {branch_name} {remote_dir}")
        self.run_cmd_on_bootstrap_vm([clone_cmd])

    @e2e_utils.retry_on_error()
    def run_cmd_on_k8s_node(self, cmd, node_address):
        cmd = ["ssh", node_address, f"'{cmd}'"]
        return e2e_utils.run_shell_cmd(cmd, timeout=600)

    @e2e_utils.retry_on_error()
    def download_from_k8s_node(self, remote_path, local_path, node_address):
        cmd = ["scp", "-r", f"{node_address}:{remote_path}", local_path]
        e2e_utils.run_shell_cmd(cmd, timeout=600)

    @e2e_utils.retry_on_error()
    def upload_to_k8s_node(self, local_path, remote_path, node_address):
        cmd = ["scp", "-r", local_path, f"{node_address}:{remote_path}"]
        e2e_utils.run_shell_cmd(cmd, timeout=600)

    def check_k8s_node_connection(self, node_address):
        cmd = ["ssh", self.master_public_address,
               f"'nc -w 5 -z {node_address} 22'"]
        try:
            e2e_utils.run_shell_cmd(cmd, sensitive=True, timeout=60)
        except e2e_exceptions.ShellCmdFailed:
            return False
        return True

    def collect_bootstrap_vm_logs(self):
        self.logging.info("Collecting logs from bootstrap VM")
        os.makedirs(self.bootstrap_vm_logs_dir, exist_ok=True)
        output, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
            self.kubectl, "get", "pods",
            "--kubeconfig", self.mgmt_kubeconfig_path,
            "-A", "-o", "yaml"], sensitive=True)
        pods = yaml.safe_load(output)
        for pod in pods['items']:
            name = pod['metadata']['name']
            ns = pod['metadata']['namespace']
            for container in pod['spec']['containers']:
                container_name = container['name']
                out, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
                    self.kubectl, "logs",
                    "--kubeconfig", self.mgmt_kubeconfig_path,
                    "-n", ns, name, container_name], sensitive=True)
                log_file = os.path.join(
                    self.bootstrap_vm_logs_dir,
                    f"{ns}_{name}_{container_name}.log")
                with open(log_file, 'wb') as f:
                    f.write(out)
        e2e_utils.make_tgz_archive(
            self.bootstrap_vm_logs_dir,
            f"{self.bootstrap_vm_logs_dir}.tgz")
        shutil.rmtree(self.bootstrap_vm_logs_dir)

    def wait_windows_agents(self, timeout=5400):
        self.logging.info(
            "Waiting up to %.2f minutes for the Windows agents",
            timeout / 60.0)
        self._wait_for_running_capz_machines(
            wanted_count=2,
            selector="cluster.x-k8s.io/deployment-name={}-md-win".format(
                self.opts.cluster_name),
            timeout=timeout)
        self.logging.info("Windows agents are ready")

    def setup_ssh_config(self):
        ssh_dir = os.path.join(os.environ["HOME"], ".ssh")
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
        ssh_config = [
            f"Host {self.master_public_address}",
            f"HostName {self.master_public_address}",
            "User capi",
            "StrictHostKeyChecking no",
            "UserKnownHostsFile /dev/null",
            f"IdentityFile {os.environ['SSH_KEY']}",
            ""
        ]
        agents_private_addresses = \
            self.windows_private_addresses + self.linux_private_addresses
        for address in agents_private_addresses:
            ssh_config += [
                f"Host {address}",
                f"HostName {address}",
                "User capi",
                f"ProxyCommand ssh -q {self.master_public_address} -W %h:%p",
                "StrictHostKeyChecking no",
                "UserKnownHostsFile /dev/null",
                f"IdentityFile {os.environ['SSH_KEY']}",
                ""
            ]
        ssh_config_file = os.path.join(ssh_dir, "config")
        with open(ssh_config_file, "w") as f:
            f.write("\n".join(ssh_config))

    def _delete_resource_group(self, resource_group_name, wait=True):
        self.logging.info("Deleting resource group %s", resource_group_name)
        client = self.resource_mgmt_client
        try:
            delete_async_operation = e2e_utils.retry_on_error()(
                client.resource_groups.begin_delete)(resource_group_name)
            if wait:
                delete_async_operation.wait()
        except azure_exceptions.ResourceNotFoundError as e:
            if e.error.code == "ResourceGroupNotFound":
                self.logging.warning(
                    "Resource group %s does not exist", resource_group_name)
            else:
                raise e

    def _get_agents_private_addresses(self, operating_system):
        cmd = [
            self.kubectl, "get", "nodes", "--kubeconfig",
            self.capz_kubeconfig_path, "-o", "yaml"
        ]
        output, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)(
            cmd, sensitive=True)
        addresses = []
        nodes = yaml.safe_load(output)
        for node in nodes['items']:
            node_os = node['status']['nodeInfo']['operatingSystem']
            if node_os != operating_system:
                continue
            try:
                node_addresses = [
                    n['address'] for n in node['status']['addresses']
                    if n['type'] == 'InternalIP'
                ]
            except Exception as ex:
                self.logging.warning(
                    "Cannot find private address for node %s. Exception "
                    "details: %s. Skipping", node["metadata"]["name"], ex)
                continue
            # pick the first node internal address
            addresses.append(node_addresses[0])
        return addresses

    def _get_azure_credentials(self):
        credentials = ClientSecretCredential(
            client_id=os.environ["AZURE_CLIENT_ID"],
            client_secret=os.environ["AZURE_CLIENT_SECRET"],
            tenant_id=os.environ["AZURE_TENANT_ID"])
        subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
        return credentials, subscription_id

    def _wait_for_bootstrap_vm(self, timeout=900):
        self.logging.info("Waiting up to %.2f minutes for VM %s to provision",
                          timeout / 60.0, self.bootstrap_vm_name)
        valid_vm_states = ["Creating", "Updating", "Succeeded"]
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_delay(timeout),
                wait=tenacity.wait_exponential(max=30),
                retry=tenacity.retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                vm = e2e_utils.retry_on_error()(
                    self.compute_client.virtual_machines.get)(
                        self.bootstrap_vm_rg_name,
                        self.bootstrap_vm_name)
                if vm.provisioning_state not in valid_vm_states:
                    err_msg = (f"VM '{self.bootstrap_vm_name}' entered "
                               f"invalid state: '{vm.provisioning_state}'")
                    self.logging.error(err_msg)
                    raise azure_exceptions.AzureError(err_msg)
                assert vm.provisioning_state == "Succeeded"
        return vm

    @e2e_utils.retry_on_error()
    def _create_bootstrap_vm_public_ip(self):
        self.logging.info("Creating bootstrap VM public IP")
        public_ip_parameters = net_models.PublicIPAddress(
            location=self.opts.location,
            public_ip_address_version="IPv4")
        self.network_client.public_ip_addresses.begin_create_or_update(
            self.bootstrap_vm_rg_name,
            self.bootstrap_vm_public_ip_name,
            public_ip_parameters).wait()
        return self.network_client.public_ip_addresses.get(
            self.bootstrap_vm_rg_name,
            self.bootstrap_vm_public_ip_name)

    def _create_bootstrap_vm_nic(self):
        public_ip = self._create_bootstrap_vm_public_ip()
        self.logging.info("Creating bootstrap VM NIC")
        bootstrap_subnet = e2e_utils.retry_on_error()(
            self.network_client.subnets.get)(
                self.bootstrap_vm_rg_name,
                self.bootstrap_vm_vnet_name,
                self.bootstrap_vm_subnet_name)
        nic_parameters = net_models.NetworkInterface(
            location=self.opts.location,
            ip_configurations=[
                net_models.NetworkInterfaceIPConfiguration(
                    name=f"{self.bootstrap_vm_nic_name}-ipconfig",
                    subnet=bootstrap_subnet,
                    public_ip_address=public_ip)])
        e2e_utils.retry_on_error()(
            self.network_client.network_interfaces.begin_create_or_update)(
                self.bootstrap_vm_rg_name,
                self.bootstrap_vm_nic_name,
                nic_parameters).wait()
        return e2e_utils.retry_on_error()(
            self.network_client.network_interfaces.get)(
                self.bootstrap_vm_rg_name,
                self.bootstrap_vm_nic_name)

    @e2e_utils.retry_on_error()
    def _init_bootstrap_vm(self):
        self.logging.info("Initializing the bootstrap VM")
        cmd = ["mkdir -p www",
               "sudo addgroup --system docker",
               "sudo usermod -aG docker capi"]
        e2e_utils.run_remote_ssh_cmd(
            cmd=cmd, ssh_user="capi", ssh_address=self.bootstrap_vm_public_ip,
            ssh_key_path=os.environ["SSH_KEY"])
        self.upload_to_bootstrap_vm(
            local_path=os.path.join(self.e2e_runner_dir, "scripts"),
            remote_path="www/")
        e2e_utils.run_remote_ssh_cmd(
            cmd=["bash ./www/scripts/init-bootstrap-vm.sh"],
            ssh_user="capi",
            ssh_address=self.bootstrap_vm_public_ip,
            ssh_key_path=os.environ["SSH_KEY"],
            timeout=(60 * 15))

    def _create_bootstrap_azure_vm(self):
        self.logging.info("Setting up the bootstrap Azure VM")
        vm_nic = self._create_bootstrap_vm_nic()
        vm_parameters = compute_models.VirtualMachine(
            location=self.opts.location,
            os_profile=compute_models.OSProfile(
                computer_name=self.bootstrap_vm_name,
                admin_username="capi",
                linux_configuration=compute_models.LinuxConfiguration(
                    disable_password_authentication=True,
                    ssh=compute_models.SshConfiguration(
                        public_keys=[
                            compute_models.SshPublicKey(
                                key_data=os.environ["AZURE_SSH_PUBLIC_KEY"],
                                path="/home/capi/.ssh/authorized_keys"
                            )
                        ]
                    )
                )
            ),
            hardware_profile=compute_models.HardwareProfile(
                vm_size=self.bootstrap_vm_size
            ),
            storage_profile=compute_models.StorageProfile(
                image_reference=compute_models.ImageReference(
                    publisher="Canonical",
                    offer="0001-com-ubuntu-server-focal",
                    sku="20_04-lts-gen2",
                    version="latest"
                ),
                os_disk=compute_models.OSDisk(
                    create_option=(
                        compute_models.DiskCreateOptionTypes.FROM_IMAGE),
                    disk_size_gb=128
                )
            ),
            network_profile=compute_models.NetworkProfile(
                network_interfaces=[
                    compute_models.NetworkInterfaceReference(
                        id=vm_nic.id)
                ]
            )
        )
        self.logging.info("Creating bootstrap VM")
        e2e_utils.retry_on_error()(
            self.compute_client.virtual_machines.begin_create_or_update)(
                self.bootstrap_vm_rg_name,
                self.bootstrap_vm_name,
                vm_parameters).wait()
        vm = self._wait_for_bootstrap_vm()
        ip_config = e2e_utils.retry_on_error()(
            self.network_client.network_interfaces.get)(
                self.bootstrap_vm_rg_name, vm_nic.name).ip_configurations[0]
        bootstrap_vm_private_ip = ip_config.private_ip_address
        public_ip = e2e_utils.retry_on_error()(
            self.network_client.public_ip_addresses.get)(
                self.bootstrap_vm_rg_name, self.bootstrap_vm_public_ip_name)
        bootstrap_vm_public_ip = public_ip.ip_address
        self.logging.info("Waiting for bootstrap VM SSH port to be reachable")
        e2e_utils.wait_for_port_connectivity(bootstrap_vm_public_ip, 22)
        self.logging.info("Finished setting up the bootstrap VM")
        return {
            'private_ip': bootstrap_vm_private_ip,
            'public_ip': bootstrap_vm_public_ip,
            'vm': vm,
        }

    def _create_bootstrap_resource_group(self):
        self.logging.info("Creating bootstrap resource group")
        rg_params = res_models.ResourceGroup(
            location=self.opts.location,
            tags=self.resource_group_tags)
        self.resource_mgmt_client.resource_groups.create_or_update(
            self.bootstrap_vm_rg_name, rg_params)
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_delay(600),
                wait=tenacity.wait_exponential(max=30),
                retry=tenacity.retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                rg = e2e_utils.retry_on_error()(
                    self.resource_mgmt_client.resource_groups.get)(
                        self.bootstrap_vm_rg_name)
                assert rg.properties.provisioning_state == "Succeeded"

    @e2e_utils.retry_on_error()
    def _create_bootstrap_vnet(self):
        self.logging.info("Creating bootstrap Azure vNET")
        vnet_params = net_models.VirtualNetwork(
            location=self.opts.location,
            address_space=net_models.AddressSpace(
                address_prefixes=[self.bootstrap_vm_vnet_cidr_block]
            )
        )
        self.network_client.virtual_networks.begin_create_or_update(
            self.bootstrap_vm_rg_name,
            self.bootstrap_vm_vnet_name,
            vnet_params).wait()
        return self.network_client.virtual_networks.get(
            self.bootstrap_vm_rg_name,
            self.bootstrap_vm_vnet_name)

    @e2e_utils.retry_on_error()
    def _create_bootstrap_secgroup(self):
        secgroup_rules = [
            net_models.SecurityRule(
                protocol="Tcp",
                priority="1000",
                source_port_range="*",
                source_address_prefix="0.0.0.0/0",
                destination_port_range="22",
                destination_address_prefix="0.0.0.0/0",
                destination_address_prefixes=[],
                destination_application_security_groups=[],
                access=net_models.SecurityRuleAccess.allow,
                direction=net_models.SecurityRuleDirection.inbound,
                name="Allow_SSH"),
            net_models.SecurityRule(
                protocol="Tcp",
                priority="1001",
                source_port_range="*",
                source_address_prefix="0.0.0.0/0",
                destination_port_range="6443",
                destination_address_prefix="0.0.0.0/0",
                destination_address_prefixes=[],
                destination_application_security_groups=[],
                access=net_models.SecurityRuleAccess.allow,
                direction=net_models.SecurityRuleDirection.inbound,
                name="Allow_K8s_API")
        ]
        self.logging.info("Creating bootstrap Azure network security group")
        secgroup_params = net_models.NetworkSecurityGroup(
            location=self.opts.location,
            security_rules=secgroup_rules)
        nsg_client = self.network_client.network_security_groups
        nsg_client.begin_create_or_update(
            self.bootstrap_vm_rg_name,
            self.bootstrap_vm_nsg_name,
            secgroup_params).wait()
        return nsg_client.get(
            self.bootstrap_vm_rg_name,
            self.bootstrap_vm_nsg_name)

    def _create_bootstrap_subnet(self):
        self.logging.info("Creating bootstrap Azure vNET subnet")
        nsg = self._create_bootstrap_secgroup()
        subnet_params = net_models.Subnet(
            address_prefix=self.bootstrap_vm_subnet_cidr,
            network_security_group=nsg)
        e2e_utils.retry_on_error()(
            self.network_client.subnets.begin_create_or_update)(
                self.bootstrap_vm_rg_name,
                self.bootstrap_vm_vnet_name,
                self.bootstrap_vm_subnet_name,
                subnet_params).wait()
        return e2e_utils.retry_on_error()(
            self.network_client.subnets.get)(
                self.bootstrap_vm_rg_name,
                self.bootstrap_vm_vnet_name,
                self.bootstrap_vm_subnet_name)

    def _get_image_sku_k8s_release(self):
        release = self.k8s_image_version.strip("v")
        return release.replace(".", "dot")

    def _get_image_sku_windows(self):
        release = self._get_image_sku_k8s_release()
        os_version = 2019
        if self.opts.win_os == "ltsc2022":
            os_version = 2022
        sku = f"k8s-{release}-windows-{os_version}"
        if self.opts.container_runtime == "containerd":
            sku += "-containerd"
        return sku

    def _get_capz_context(self):
        control_plane_subnet_cidr = self.opts.control_plane_subnet_cidr_block
        context = {
            "cluster_name": self.opts.cluster_name,
            "bootstrap_vm_vnet_name": self.bootstrap_vm_vnet_name,
            "resource_group_tags": self.resource_group_tags,
            "vnet_cidr": self.opts.vnet_cidr_block,
            "control_plane_subnet_cidr": control_plane_subnet_cidr,
            "node_subnet_cidr": self.opts.node_subnet_cidr_block,
            "cluster_network_subnet": self.opts.cluster_network_subnet,
            "azure_location": self.opts.location,
            "azure_subscription_id": os.environ["AZURE_SUBSCRIPTION_ID"],
            "azure_tenant_id": os.environ["AZURE_TENANT_ID"],
            "azure_client_id": os.environ["AZURE_CLIENT_ID"],
            "azure_client_secret": os.environ["AZURE_CLIENT_SECRET"],
            "azure_ssh_public_key": os.environ["AZURE_SSH_PUBLIC_KEY"],
            "azure_ssh_public_key_b64": os.environ["AZURE_SSH_PUBLIC_KEY_B64"],
            "master_vm_size": self.opts.master_vm_size,
            "win_agents_count": self.opts.win_agents_count,
            "win_agent_size": self.opts.win_agent_size,
            "bootstrap_vm_address": f"{self.bootstrap_vm_private_ip}:8081",
            "kubernetes_version": self.kubernetes_version,
            "flannel_mode": self.opts.flannel_mode,
            "container_runtime": self.opts.container_runtime,
            "image_sku_k8s_release": self._get_image_sku_k8s_release(),
            "image_sku_windows": self._get_image_sku_windows(),
            "k8s_bins": "k8sbins" in self.bins_built,
            "sdn_cni_bins": "sdncnibins" in self.bins_built,
            "containerd_bins": "containerdbins" in self.bins_built,
            "containerd_shim_bins": "containerdshim" in self.bins_built,
        }
        return context

    def _create_capz_cluster(self):
        self.logging.info("Create CAPZ cluster")
        output_file = "/tmp/capz-cluster.yaml"
        context = self._get_capz_context()
        e2e_utils.render_template(
            "cluster.yaml.j2", output_file, context, self.capz_dir)
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)([
            self.kubectl, "apply", "--kubeconfig",
            self.mgmt_kubeconfig_path, "-f", output_file
        ])

    def _wait_capz_control_plane(self, timeout=1800):
        self.logging.info(
            "Waiting up to %.2f minutes for the CAPZ control-plane",
            timeout / 60.0)
        self._wait_for_running_capz_machines(
            wanted_count=1,
            selector="cluster.x-k8s.io/control-plane=",
            timeout=timeout)
        self.logging.info("Control-plane is ready")

    def _setup_mgmt_kubeconfig(self):
        self.logging.info("Setting up the management cluster kubeconfig")
        self.download_from_bootstrap_vm(
            ".kube/config", self.mgmt_kubeconfig_path)
        with open(self.mgmt_kubeconfig_path, 'r') as f:
            cfg = yaml.safe_load(f.read())
        public_endpoint = f"https://{self.bootstrap_vm_public_ip}:6443"
        cfg["clusters"][0]["cluster"]["server"] = public_endpoint
        with open(self.mgmt_kubeconfig_path, 'w') as f:
            f.write(yaml.safe_dump(cfg))

    def _parse_capz_kubeconfig(self):
        with open(self.capz_kubeconfig_path, 'r') as f:
            cfg = yaml.safe_load(f.read())
        endpoint = urlparse(cfg["clusters"][0]["cluster"]["server"])
        k8s_address = endpoint.hostname
        k8s_port = endpoint.port
        if k8s_port is None:
            if endpoint.scheme == "http":
                k8s_port = 80
            elif endpoint.scheme == "https":
                k8s_port = 443
            else:
                raise Exception(
                    f"Unknown k8s endpoint scheme: {endpoint.scheme}")
        return k8s_address, k8s_port

    @e2e_utils.retry_on_error()
    def _setup_capz_kubeconfig(self):
        self.logging.info("Setting up CAPZ kubeconfig")
        output, _ = e2e_utils.run_shell_cmd([
            "clusterctl", "get", "kubeconfig",
            "--kubeconfig", self.mgmt_kubeconfig_path,
            self.opts.cluster_name
        ])
        with open(self.capz_kubeconfig_path, 'w') as f:
            f.write(output.decode())

    def _wait_for_running_machinepool(
            self, name, selector="", timeout=3600):

        cmd = [
            self.kubectl, "get", "machinepool", name,
            "--kubeconfig", self.mgmt_kubeconfig_path,
            "-l", f"'{selector}'",
            "-o", "yaml"
        ]
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_delay(timeout),
                wait=tenacity.wait_exponential(max=30),
                retry=tenacity.retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                out, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)(
                    cmd, sensitive=True)
                machine_pool = yaml.safe_load(out.decode())
                status = machine_pool.get("status")
                assert status is not None, "Machine pool status is None"
                replicas = status.get("replicas")
                ready_replicas = status.get("readyReplicas")
                assert replicas == ready_replicas, (
                    f"Machine pool replicas ({replicas}) != "
                    f"ready replicas ({ready_replicas})")
                phase = status.get("phase")
                assert phase == "Running", (
                    f"Machine pool phase ({phase}) != Running")

    def _wait_for_running_capz_machines(
            self, wanted_count, selector="", timeout=3600):

        cmd = [
            self.kubectl, "get", "machine",
            "--kubeconfig", self.mgmt_kubeconfig_path,
            "-l", f"'{selector}'",
            "-o", "yaml"
        ]
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_delay(timeout),
                wait=tenacity.wait_exponential(max=30),
                retry=tenacity.retry_if_exception_type(AssertionError),
                reraise=True):
            with attempt:
                out, _ = e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)(
                    cmd, sensitive=True)
                machines = yaml.safe_load(out.decode())
                running_machines = []
                for machine in machines["items"]:
                    status = machine.get("status")
                    if not status:
                        continue
                    if status.get("phase") == "Running":
                        running_machines.append(machine)
                assert len(running_machines) == wanted_count, (
                    f"Expected {wanted_count} running CAPZ machines, "
                    f"but found {len(running_machines)}")

    def _setup_capz_components(self):
        self.logging.info("Creating CAPI cluster identity")
        client_secret = os.environ["AZURE_CLIENT_SECRET"]
        cmd = [
            self.kubectl, "create",
            "--kubeconfig", self.mgmt_kubeconfig_path,
            "secret", "generic",
            "cluster-identity-secret",
            f"--from-literal=clientSecret='{client_secret}'"
        ]
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)(
            cmd, sensitive=True)
        self.logging.info("Setup the Azure Cluster API components")
        e2e_utils.retry_on_error()(e2e_utils.run_shell_cmd)(
            cmd=[
                "clusterctl", "init",
                "--kubeconfig", self.mgmt_kubeconfig_path,
                "--infrastructure", "azure:v1.3.0",
                "--wait-providers",
            ],
            env={
                "GITHUB_TOKEN": os.environ["GITHUB_TOKEN"],
            })

    def _set_azure_variables(self):
        # Define the required env variables list
        required_env_vars = [
            "AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET", "AZURE_SSH_PUBLIC_KEY"
        ]
        # Check for alternate env variables names set in the CI if
        # the expected ones are empty
        if (not os.environ.get("AZURE_SUBSCRIPTION_ID")
                and os.environ.get("AZURE_SUB_ID")):
            os.environ["AZURE_SUBSCRIPTION_ID"] = os.environ.get(
                "AZURE_SUB_ID")
        if (not os.environ.get("AZURE_SSH_PUBLIC_KEY")
                and os.environ.get("SSH_KEY_PUB")):
            with open(os.environ.get("SSH_KEY_PUB").strip()) as f:
                os.environ["AZURE_SSH_PUBLIC_KEY"] = f.read().strip()
        # Check if the required env variables are set, and set their
        # base64 variants
        for env_var in required_env_vars:
            if not os.environ.get(env_var):
                raise Exception(f"Env variable {env_var} is not set")
            os.environ[env_var] = os.environ.get(env_var).strip()
            b64_env_var = f"{env_var}_B64"
            os.environ[b64_env_var] = base64.b64encode(
                os.environ.get(env_var).encode()).decode()
        # Set Azure location if it's not set already
        if not self.opts.location:
            self.opts.location = random.choice(
                e2e_constants.AZURE_LOCATIONS)
        self.logging.info("Using Azure location %s", self.opts.location)
