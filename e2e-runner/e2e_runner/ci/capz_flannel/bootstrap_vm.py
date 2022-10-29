import base64
import os
import subprocess

import tenacity
from azure.core import exceptions as azure_exceptions
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute import models as compute_models
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network import models as net_models
from azure.mgmt.resource import ResourceManagementClient
from e2e_runner import logger as e2e_logger
from e2e_runner.utils import azure as e2e_azure_utils
from e2e_runner.utils import utils as e2e_utils


class BootstrapVM(object):
    VM_USER = "capi"

    def __init__(self, opts, location=None):
        self.logging = e2e_logger.get_logger(__name__)
        self.current_dir = os.path.dirname(__file__)

        self.location = location
        self.rg_name = f"{opts.cluster_name}-bootstrap"
        self.rg_tags = e2e_azure_utils.get_resource_group_tags()
        self.vm_info = {}
        self.vm_name = "k8s-bootstrap"
        self.vm_size = opts.bootstrap_vm_size
        self.vnet_name = "k8s-bootstrap-vnet"
        self.vnet_cidr_block = "192.168.0.0/16"
        self.subnet_name = "k8s-bootstrap-subnet"
        self.subnet_cidr = "192.168.0.0/24"
        self.nsg_name = "k8s-bootstrap-nsg"
        self.nic_name = "k8s-bootstrap-nic"
        self.public_ip_name = "k8s-bootstrap-public-ip"
        self.logs_dir = os.path.join(
            opts.artifacts_directory, "bootstrap_vm_logs")

        self.ssh_private_key_path = os.environ["SSH_PRIVATE_KEY_PATH"]
        self.ssh_public_key = e2e_utils.get_file_content(
            os.environ["SSH_PUBLIC_KEY_PATH"])

        creds, sub_id = e2e_azure_utils.get_credentials()
        self.mgmt_client = ResourceManagementClient(creds, sub_id)
        self.network_client = NetworkManagementClient(creds, sub_id)
        self.compute_client = ComputeManagementClient(creds, sub_id)

    @property
    def is_deployed(self):
        return len(self.vm_info) > 0

    @property
    def private_ip(self):
        return self.vm_info["private_ip"]

    @property
    def public_ip(self):
        return self.vm_info["public_ip"]

    @property
    def go_path(self):
        return "~/go"

    @property
    def artifacts_dir(self):
        return "~/www"

    @e2e_utils.retry_on_error()
    def setup(self):
        self.logging.info("Setting up the bootstrap VM")

        try:
            self._create_rg()
            self._create_vnet()
            self._create_vnet_subnet()
            self._create_azure_vm()
            self._init_azure_vm()
        except Exception as ex:
            self._delete_rg()
            raise ex

        self.logging.info("Finished setting up the bootstrap VM")

    def remove(self, wait=False):
        self.logging.info("Remove bootstrap VM resource group")
        self._delete_rg(wait=wait)
        self._reset_vm_info()

    @e2e_utils.retry_on_error()
    def upload(self, local_path, remote_path):
        e2e_utils.rsync_upload(
            local_path=local_path,
            remote_path=remote_path,
            ssh_user=self.VM_USER,
            ssh_address=self.public_ip,
            ssh_key_path=self.ssh_private_key_path)

    @e2e_utils.retry_on_error()
    def download(self, remote_path, local_path):
        e2e_utils.rsync_download(
            remote_path=remote_path,
            local_path=local_path,
            ssh_user=self.VM_USER,
            ssh_address=self.public_ip,
            ssh_key_path=self.ssh_private_key_path)

    def exec(self, script, return_result=False, cwd="~", timeout=3600):
        kwargs = {
            "ssh_user": self.VM_USER,
            "ssh_address": self.public_ip,
            "ssh_key_path": self.ssh_private_key_path,
            "return_result": return_result,
            "cwd": cwd,
            "timeout": timeout,
        }
        return e2e_utils.run_remote_ssh_cmd(script, **kwargs)

    @e2e_utils.retry_on_error()
    def cleanup_vnet_peerings(self):
        peerings_client = self.network_client.virtual_network_peerings
        for peering in peerings_client.list(self.rg_name, self.vnet_name):
            self.logging.info(
                "Deleting bootstrap vNET peering: %s", peering.name)
            peerings_client.begin_delete(
                self.rg_name,
                self.vnet_name,
                peering.name).wait()  # pyright: ignore

    def clone_git_repo(self, url, branch_name, dir):
        self.exec([f"test -e {dir} || "
                   f"git clone --single-branch {url} --branch {branch_name} {dir}"])  # noqa:

    def _set_vm_info(self):
        self.vm_info = {
            "private_ip": self._get_vm_private_ip(),
            "public_ip": self._get_vm_public_ip(),
        }

    def _reset_vm_info(self):
        self.vm_info = {}

    def _create_rg(self):
        e2e_azure_utils.create_resource_group(
            client=self.mgmt_client,
            name=self.rg_name,
            location=self.location,
            tags=self.rg_tags)

    def _delete_rg(self, wait=True):
        e2e_azure_utils.delete_resource_group(
            self.mgmt_client,
            self.rg_name,
            wait=wait)

    def _create_vnet(self):
        self.logging.info("Creating bootstrap Azure vNET")
        vnet_params = net_models.VirtualNetwork(
            location=self.location,
            address_space=net_models.AddressSpace(
                address_prefixes=[self.vnet_cidr_block]
            )
        )
        e2e_utils.retry_on_error()(
            self.network_client.virtual_networks.begin_create_or_update)(
                self.rg_name,
                self.vnet_name,
                vnet_params).wait()  # pyright: ignore
        return e2e_utils.retry_on_error()(
            self.network_client.virtual_networks.get)(
                self.rg_name,
                self.vnet_name)

    def _create_vnet_subnet(self):
        self.logging.info("Creating bootstrap Azure vNET subnet")
        nsg = self._create_secgroup()
        subnet_params = net_models.Subnet(
            address_prefix=self.subnet_cidr,
            network_security_group=nsg)  # pyright: ignore
        e2e_utils.retry_on_error()(
            self.network_client.subnets.begin_create_or_update)(
                self.rg_name,
                self.vnet_name,
                self.subnet_name,
                subnet_params).wait()  # pyright: ignore
        return e2e_utils.retry_on_error()(
            self.network_client.subnets.get)(
                self.rg_name,
                self.vnet_name,
                self.subnet_name)

    def _create_secgroup(self):
        secgroup_rules = [
            net_models.SecurityRule(
                protocol="Tcp",
                priority=1000,
                source_port_range="*",
                source_address_prefix="0.0.0.0/0",
                destination_port_range="22",
                destination_address_prefix="0.0.0.0/0",
                destination_address_prefixes=[],
                destination_application_security_groups=[],
                access=net_models.SecurityRuleAccess.ALLOW,
                direction=net_models.SecurityRuleDirection.INBOUND,
                name="Allow_SSH"),
            net_models.SecurityRule(
                protocol="Tcp",
                priority=1001,
                source_port_range="*",
                source_address_prefix="0.0.0.0/0",
                destination_port_range="6443",
                destination_address_prefix="0.0.0.0/0",
                destination_address_prefixes=[],
                destination_application_security_groups=[],
                access=net_models.SecurityRuleAccess.ALLOW,
                direction=net_models.SecurityRuleDirection.INBOUND,
                name="Allow_K8s_API")
        ]
        self.logging.info("Creating bootstrap Azure network security group")
        secgroup_params = net_models.NetworkSecurityGroup(
            location=self.location,
            security_rules=secgroup_rules)
        nsg_client = self.network_client.network_security_groups
        e2e_utils.retry_on_error()(
            nsg_client.begin_create_or_update)(
                self.rg_name,
                self.nsg_name,
                secgroup_params).wait()  # pyright: ignore
        return e2e_utils.retry_on_error()(
            nsg_client.get)(
                self.rg_name,
                self.nsg_name)

    def _create_azure_vm(self):
        self.logging.info("Setting up the bootstrap Azure VM")

        vm_nic = self._create_vm_nic()
        e2e_utils.retry_on_error()(
            self.compute_client.virtual_machines.begin_create_or_update)(
                self.rg_name,
                self.vm_name,
                self._get_vm_profile(vm_nic)).wait()  # pyright: ignore
        self._wait_for_vm()

        self.logging.info("Waiting for bootstrap VM SSH port to be reachable")
        e2e_utils.wait_for_port_connectivity(self._get_vm_public_ip(), 22)

        self._set_vm_info()

    def _create_vm_nic(self):
        public_ip = self._create_vm_public_ip()
        self.logging.info("Creating bootstrap VM NIC")
        subnet = e2e_utils.retry_on_error()(
            self.network_client.subnets.get)(
                self.rg_name,
                self.vnet_name,
                self.subnet_name)
        nic_parameters = net_models.NetworkInterface(
            location=self.location,
            ip_configurations=[
                net_models.NetworkInterfaceIPConfiguration(
                    name=f"{self.nic_name}-ipconfig",
                    subnet=subnet,  # pyright: ignore
                    public_ip_address=public_ip,  # pyright: ignore
                )
            ])
        e2e_utils.retry_on_error()(
            self.network_client.network_interfaces.begin_create_or_update)(
                self.rg_name,
                self.nic_name,
                nic_parameters).wait()  # pyright: ignore
        return e2e_utils.retry_on_error()(
            self.network_client.network_interfaces.get)(
                self.rg_name,
                self.nic_name)

    def _create_vm_public_ip(self):
        self.logging.info("Creating bootstrap VM public IP")
        public_ip_parameters = net_models.PublicIPAddress(
            location=self.location,
            public_ip_address_version="IPv4")
        e2e_utils.retry_on_error()(
            self.network_client.public_ip_addresses.begin_create_or_update)(
                self.rg_name,
                self.public_ip_name,
                public_ip_parameters).wait()  # pyright: ignore
        return e2e_utils.retry_on_error()(
            self.network_client.public_ip_addresses.get)(
                self.rg_name,
                self.public_ip_name)

    def _get_vm_profile(self, vm_nic):
        userdata_file = os.path.join(self.current_dir, "cloud-init/userdata")
        with open(userdata_file, "r") as f:
            userdata = f.read()
        userdata_encoded = base64.b64encode(userdata.encode()).decode()
        return compute_models.VirtualMachine(
            location=self.location,
            os_profile=self._get_os_profile(),
            user_data=userdata_encoded,
            hardware_profile=self._get_hardware_profile(),
            storage_profile=self._get_storage_profile(),
            network_profile=self._get_network_profile(vm_nic),
        )

    def _get_os_profile(self):
        return compute_models.OSProfile(
            computer_name=self.vm_name,
            admin_username=self.VM_USER,
            linux_configuration=compute_models.LinuxConfiguration(
                disable_password_authentication=True,
                ssh=compute_models.SshConfiguration(
                    public_keys=[
                        compute_models.SshPublicKey(
                            key_data=self.ssh_public_key,
                            path=f"/home/{self.VM_USER}/.ssh/authorized_keys",
                        )
                    ]
                )
            )
        )

    def _get_hardware_profile(self):
        return compute_models.HardwareProfile(
            vm_size=self.vm_size
        )

    def _get_storage_profile(self):
        return compute_models.StorageProfile(
            image_reference=compute_models.ImageReference(
                publisher="Canonical",
                offer="0001-com-ubuntu-server-focal",
                sku="20_04-lts-gen2",
                version="latest",
            ),
            os_disk=compute_models.OSDisk(
                create_option=compute_models.DiskCreateOptionTypes.FROM_IMAGE,
                disk_size_gb=128,
            )
        )

    def _get_network_profile(self, vm_nic):
        return compute_models.NetworkProfile(
            network_interfaces=[
                compute_models.NetworkInterfaceReference(id=vm_nic.id)
            ]
        )

    def _wait_for_vm(self, timeout=900):
        self.logging.info("Waiting up to %.2f minutes for VM %s to provision",
                          timeout / 60.0, self.vm_name)
        valid_vm_states = ["Creating", "Updating", "Succeeded"]
        vm = None
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_delay(timeout),  # pyright: ignore
                wait=tenacity.wait_exponential(max=30),  # pyright: ignore
                retry=tenacity.retry_if_exception_type(AssertionError),  # pyright: ignore # noqa:
                reraise=True):
            with attempt:
                vm = e2e_utils.retry_on_error()(
                    self.compute_client.virtual_machines.get)(
                        self.rg_name,
                        self.vm_name)
                if vm.provisioning_state not in valid_vm_states:  # pyright: ignore # noqa
                    err_msg = (f"VM '{self.vm_name}' entered "
                               f"invalid state: '{vm.provisioning_state}'")
                    self.logging.error(err_msg)
                    raise azure_exceptions.AzureError(err_msg)
                assert vm.provisioning_state == "Succeeded"

    def _get_vm_private_ip(self):
        nic = e2e_utils.retry_on_error()(
            self.network_client.network_interfaces.get)(
                self.rg_name,
                self.nic_name)
        return nic.ip_configurations[0].private_ip_address  # pyright: ignore

    def _get_vm_public_ip(self):
        public_ip = e2e_utils.retry_on_error()(
            self.network_client.public_ip_addresses.get)(
                self.rg_name,
                self.public_ip_name)
        return public_ip.ip_address

    def _init_azure_vm(self):
        self._wait_cloud_init_complete()
        self._setup_www()
        self._install_golang()
        self._install_kind()

    def _wait_cloud_init_complete(self, timeout=600):
        self.logging.info("Wait until bootstrap VM cloud-init is completed")
        for attempt in tenacity.Retrying(
                stop=tenacity.stop_after_delay(timeout),  # pyright: ignore
                wait=tenacity.wait_exponential(max=30),  # pyright: ignore
                retry=tenacity.retry_if_exception_type(subprocess.CalledProcessError),  # pyright: ignore # noqa:
                reraise=True):
            with attempt:
                self.exec(["test -e /cloud-init-complete"])

    @e2e_utils.retry_on_error()
    def _setup_www(self):
        self.logging.info("Setup bootstrap VM file share")
        self.exec([
            f"mkdir -p {self.artifacts_dir}",
            ("docker run --name nginx --restart unless-stopped -p 8081:80 "
             f"-v {self.artifacts_dir}:/usr/share/nginx/html:ro "
             "-d nginx:stable"),
        ])

    @e2e_utils.retry_on_error()
    def _install_golang(self):
        self.logging.info("Install Golang on bootstrap VM")
        script_file = os.path.join(
            self.current_dir, "cloud-init/install-golang.sh")
        self.upload(script_file, "/tmp/install-golang.sh")
        self.exec(["bash /tmp/install-golang.sh"])

    @e2e_utils.retry_on_error()
    def _install_kind(self):
        self.logging.info("Install KIND on bootstrap VM")
        script_file = os.path.join(
            self.current_dir, "cloud-init/install-kind.sh")
        self.upload(script_file, "/tmp/install-kind.sh")
        self.exec(["bash /tmp/install-kind.sh"])
