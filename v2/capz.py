import base64
import os
import random
import time

from distutils.util import strtobool

import configargparse
import msrestazure
import yaml

import sh
from azure.common.credentials import ServicePrincipalCredentials
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.network import models as net_models
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.compute import ComputeManagementClient
from property_cached import cached_property

import constants
import deployer
import log
import utils

p = configargparse.get_argument_parser()

p.add("--cluster-name",
      required=True,
      help="The cluster name given to the cluster-api manifest. "
      "This value is used for the Azure resource group name as well.")
p.add("--cluster-network-subnet",
      default="10.244.0.0/16",
      help="The cluster network subnet given to the cluster-api manifest")
p.add("--location", help="The Azure location for the spawned resource.")
p.add("--bootstrap-vm-size", default="Standard_B1ms",
      help="Size of the bootstrap VM")
p.add("--master-vm-size",
      default="Standard_D2s_v3",
      help="Size of master virtual machine.")
p.add("--win-minion-count",
      type=int,
      default=2,
      help="Number of Windows minions for the deployment.")
p.add("--win-minion-size",
      default="Standard_D2s_v3",
      help="Size of Windows minions.")
p.add("--win-minion-gallery-image",
      required=True,
      help="The Windows minion shared gallery. The parameter shall be given "
      "as: <IMG_GALLERY_RG>:<IMG_GALLERY_NAME>:<IMG_DEFINITION>:<IMG_VERSION>")


class CAPZProvisioner(deployer.NoopDeployer):
    def __init__(self, flannel_mode=constants.FLANNEL_MODE_OVERLAY,
                 container_runtime="docker"):
        super(CAPZProvisioner, self).__init__()

        self.logging = log.getLogger(__name__)
        self.kubectl = utils.get_kubectl_bin()
        self.flannel_mode = flannel_mode
        self.container_runtime = container_runtime

        opts = p.parse_known_args()[0]
        self.cluster_name = opts.cluster_name
        self.cluster_network_subnet = opts.cluster_network_subnet
        self.azure_location = opts.location
        self.master_vm_size = opts.master_vm_size

        self.win_minion_count = opts.win_minion_count
        self.win_minion_size = opts.win_minion_size
        parsed = self._parse_win_minion_image_gallery(
            opts.win_minion_gallery_image)
        self.win_minion_image_rg = parsed["resource_group"]
        self.win_minion_image_gallery = parsed["gallery_name"]
        self.win_minion_image_definition = parsed["image_definition"]
        self.win_minion_image_version = parsed["image_version"]

        self.kind_kubeconfig_path = "/tmp/kind-kubeconfig.yaml"
        self.capz_kubeconfig_path = "/tmp/capz-kubeconfig.yaml"

        self.ci_version = None  # set by the CI class before calling up()
        self.ci_artifacts_dir = None  # set by the CI class before calling up()

        self.bootstrap_vm_name = "k8s-bootstrap"
        self.bootstrap_vm_secgroup_name = "k8s-bootstrap-nsg"
        self.bootstrap_vm_nic_name = "k8s-bootstrap-nic"
        self.bootstrap_vm_public_ip_name = "k8s-bootstrap-public-ip"
        self.bootstrap_vm_size = opts.bootstrap_vm_size
        self.bootstrap_vm_public_ip = None   # set by _create_bootstrap_vm()
        self.bootstrap_vm_private_ip = None  # set by _create_bootstrap_vm()

        self._set_azure_variables()
        credentials, subscription_id = self._get_azure_credentials()

        self.resource_mgmt_client = ResourceManagementClient(
            credentials, subscription_id)
        self.network_client = NetworkManagementClient(credentials,
                                                      subscription_id)
        self.compute_client = ComputeManagementClient(credentials,
                                                      subscription_id)

    @cached_property
    def master_public_address(self):
        output, _ = utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "get", "cluster", "--kubeconfig",
            self.kind_kubeconfig_path, self.cluster_name, "-o",
            "custom-columns=MASTER_ADDRESS:.spec.controlPlaneEndpoint.host",
            "--no-headers"
        ])
        return output.decode("ascii").strip()

    @cached_property
    def master_public_port(self):
        output, _ = utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "get", "cluster", "--kubeconfig",
            self.kind_kubeconfig_path, self.cluster_name, "-o",
            "custom-columns=MASTER_PORT:.spec.controlPlaneEndpoint.port",
            "--no-headers"
        ])
        return output.decode("ascii").strip()

    @cached_property
    def linux_private_addresses(self):
        return self._get_agents_private_addresses("linux")

    @cached_property
    def windows_private_addresses(self):
        return self._get_agents_private_addresses("windows")

    def up(self):
        if not self.ci_version:
            raise Exception("The variable ci_version must be set before "
                            "calling the deployer up() method")

        if not self.ci_artifacts_dir:
            raise Exception("The variable ci_artifacts_dir must be set "
                            "before calling the deployer up() method")

        self._create_kind_cluster()
        self._create_capz_cluster()
        self._wait_for_control_plane()

        if self.flannel_mode == constants.FLANNEL_MODE_L2BRIDGE:
            self._connect_control_plane_to_node_subnet()

        self._setup_capz_kubeconfig()

    def down(self):
        self.logging.info("Deleting kind cluster")
        utils.run_shell_cmd(["kind", "delete", "cluster"])

        self.logging.info("Deleting Azure resource group")
        client = self.resource_mgmt_client
        try:
            delete_async_operation = client.resource_groups.delete(
                self.cluster_name)
            delete_async_operation.wait()
        except msrestazure.azure_exceptions.CloudError as e:
            cloud_error_data = e.error
            if cloud_error_data.error == "ResourceGroupNotFound":
                self.logging.warning("Resource group %s does not exist",
                                     self.cluster_name)
            else:
                raise e

    def reclaim(self):
        self._setup_capz_kubeconfig()

    def setup_ssh_config(self):
        ssh_dir = os.path.join(os.environ["HOME"], ".ssh")
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)

        ssh_config = [
            "Host %s" % self.master_public_address,
            "HostName %s" % self.master_public_address,
            "User capi",
            "StrictHostKeyChecking no",
            "UserKnownHostsFile /dev/null",
            "IdentityFile %s" % os.environ["SSH_KEY"],
            ""
        ]

        k8s_master_ssh_host = self.master_public_address
        agents_private_addresses = self.windows_private_addresses + \
            self.linux_private_addresses
        for address in agents_private_addresses:
            ssh_config += [
                "Host %s" % address,
                "HostName %s" % address,
                "User capi",
                "ProxyCommand ssh -q %s -W %%h:%%p" % k8s_master_ssh_host,
                "StrictHostKeyChecking no",
                "UserKnownHostsFile /dev/null",
                "IdentityFile %s" % os.environ["SSH_KEY"],
                ""
            ]

        ssh_config_file = os.path.join(ssh_dir, "config")
        with open(ssh_config_file, "w") as f:
            f.write("\n".join(ssh_config))

    def enable_ip_forwarding(self):
        self.logging.info("Enabling IP forwarding for the cluster VMs")

        vm_nics = utils.retry_on_error()(
            self.network_client.network_interfaces.list)(self.cluster_name)
        for nic in vm_nics:
            if nic.name == self.bootstrap_vm_nic_name:
                continue

            if nic.enable_ip_forwarding:
                self.logging.info(
                    "IP forwarding is already enabled on nic %s", nic.name)
                continue

            self.logging.info("Enabling IP forwarding on nic %s", nic.name)

            nic_parameters = nic.as_dict()
            nic_parameters["enable_ip_forwarding"] = True
            utils.retry_on_error()(
                self.network_client.network_interfaces.create_or_update)(
                    self.cluster_name,
                    nic.name,
                    nic_parameters).result()

    def wait_for_agents(self, check_nodes_ready=True, timeout=3600):
        self._wait_for_windows_agents(check_nodes_ready=check_nodes_ready,
                                      timeout=timeout)

    def upload_to_bootstrap_vm(self, local_path):
        self.logging.info("Uploading %s to bootstrap VM", local_path)

        ssh_cmd = ("ssh -i %s -o StrictHostKeyChecking=no "
                   "-o UserKnownHostsFile=/dev/null" % os.environ["SSH_KEY"])
        cmd = ["rsync", "--chmod=D755,F644", "-r", "-e",
               "\"%s\"" % ssh_cmd, local_path,
               "capi@%s:/www/" % self.bootstrap_vm_public_ip]

        utils.retry_on_error()(utils.run_shell_cmd)(cmd)

    def run_cmd_on_k8s_node(self, cmd, node_address):
        return utils.run_shell_cmd(["ssh", node_address, "'%s'" % cmd])

    def run_async_cmd_on_k8s_node(self, cmd, node_address):
        return utils.run_async_shell_cmd(
            sh.ssh, [node_address, cmd])

    def download_from_k8s_node(self, remote_path, local_path,
                               node_address, timeout="10m"):
        self.logging.info("Downloading %s to %s from node %s",
                          remote_path, local_path, node_address)
        utils.run_shell_cmd([
            "timeout", timeout, "scp",
            "-r", "%s:%s" % (node_address, remote_path), local_path])

    def upload_to_k8s_node(self, local_path, remote_path,
                           node_address, timeout="10m"):
        self.logging.info("Uploading %s to %s on node %s",
                          local_path, remote_path, node_address)
        utils.run_shell_cmd([
            "timeout", timeout, "scp",
            "-r", local_path, "%s:%s" % (node_address, remote_path)])

    def check_k8s_node_connection(self, node_address, timeout="1m"):
        cmd = ["timeout", timeout, "ssh", self.master_public_address,
               "'nc -w 5 -z %s 22'" % node_address]

        _, _, ret = utils.run_cmd(cmd, shell=True, sensitive=True)

        if ret == 0:
            return True

        return False

    def _get_agents_private_addresses(self, operating_system):
        output, _ = utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "get", "machine", "--kubeconfig",
            self.kind_kubeconfig_path, "-o", "yaml"
        ])
        addresses = []
        nodes = yaml.safe_load(output)
        for node in nodes['items']:
            if (operating_system == "linux" and
                    node["metadata"]["name"].startswith("capi-win")):
                continue

            if (operating_system == "windows" and
                    not node["metadata"]["name"].startswith("capi-win")):
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

            # pick the first node internal address
            addresses.append(node_addresses[0])

        return addresses

    def _parse_win_minion_image_gallery(self, win_minion_gallery_image):
        split = win_minion_gallery_image.split(":")
        if len(split) != 4:
            err_msg = ("Incorrect format for the --win-minion-image-gallery "
                       "parameter")
            self.logging.error(err_msg)
            raise Exception(err_msg)

        return {
            "resource_group": split[0],
            "gallery_name": split[1],
            "image_definition": split[2],
            "image_version": split[3]
        }

    def _get_azure_credentials(self):
        credentials = ServicePrincipalCredentials(
            client_id=os.environ["AZURE_CLIENT_ID"],
            secret=os.environ["AZURE_CLIENT_SECRET"],
            tenant=os.environ["AZURE_TENANT_ID"])
        subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
        return credentials, subscription_id

    @utils.retry_on_error()
    def _get_control_plane_vm(self):
        for vm in self.compute_client.virtual_machines.list(self.cluster_name):
            if vm.name.startswith("%s-control-plane" % self.cluster_name):
                return vm
        return None

    @utils.retry_on_error()
    def _get_control_plane_route(self):
        routes = self.network_client.routes.list(
            self.cluster_name,
            "%s-node-routetable" % self.cluster_name)
        for route in routes:
            if route.name.startswith("%s-control-plane" % self.cluster_name):
                return route
        return None

    def _connect_control_plane_to_node_subnet(self):
        self.logging.info(
            "Adding second NIC from node subnet to control plane")

        control_plane_vm = self._get_control_plane_vm()
        if not control_plane_vm:
            raise Exception("The control plane VM was not found")

        if len(control_plane_vm.network_profile.network_interfaces) > 1:
            self.logging.info(
                "The second NIC is already attached to the control plane")
            return

        nic_name = "%s-control-plane-node-nic" % self.cluster_name
        node_subnet = utils.retry_on_error()(
            self.network_client.subnets.get)(
                self.cluster_name,
                "%s-vnet" % self.cluster_name,
                "%s-node-subnet" % self.cluster_name)
        nic_parameters = {
            "location": self.azure_location,
            "ip_configurations": [{
                "name": "%s-ipconfig" % nic_name,
                "subnet": {"id": node_subnet.id}
            }]
        }
        self.logging.info("Creating the second NIC")
        nic = utils.retry_on_error()(
            self.network_client.network_interfaces.create_or_update)(
                self.cluster_name, nic_name, nic_parameters).result()

        self.logging.info("Deallocating the control plane VM")
        utils.retry_on_error()(
            self.compute_client.virtual_machines.deallocate)(
                self.cluster_name, control_plane_vm.name).wait()

        self.logging.info("Attaching the second NIC to the control plane VM")
        vm_parameters = control_plane_vm.as_dict()
        vm_parameters["network_profile"]["network_interfaces"].append(
            {"id": nic.id, "primary": False})
        utils.retry_on_error()(
            self.compute_client.virtual_machines.create_or_update)(
                self.cluster_name, control_plane_vm.name, vm_parameters).wait()

        self.logging.info("Starting the control plane VM")
        utils.retry_on_error()(
            self.compute_client.virtual_machines.start)(
                self.cluster_name, control_plane_vm.name).wait()
        utils.wait_for_port_connectivity(self.master_public_address, 22)

        self.logging.info("Updating the control plane route")
        control_plane_route = self._get_control_plane_route()
        if not control_plane_route:
            raise Exception("The control plane route was not found")
        route_params = control_plane_route.as_dict()
        route_params["next_hop_ip_address"] = \
            nic.ip_configurations[0].private_ip_address
        utils.retry_on_error()(
            self.network_client.routes.create_or_update)(
                self.cluster_name,
                "%s-node-routetable" % self.cluster_name,
                control_plane_route.name,
                route_params).wait()

    def _wait_for_bootstrap_vm(self, timeout=900):
        self.logging.info("Waiting up to %.2f minutes for VM %s to provision",
                          timeout / 60.0, self.bootstrap_vm_name)

        sleep_time = 5
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                err_msg = "VM %s didn't provision within %.2f minutes" % (
                    self.bootstrap_vm_name, timeout / 60)
                self.logging.error(err_msg)
                raise Exception(err_msg)

            vm = utils.retry_on_error()(
                self.compute_client.virtual_machines.get)(
                    self.cluster_name,
                    self.bootstrap_vm_name)

            if vm.provisioning_state == "Succeeded":
                break

            if vm.provisioning_state not in ("Creating", "Updating"):
                err_msg = 'VM "%s" entered invalid state: "%s"' % (
                    self.bootstrap_vm_name, vm.provisioning_state)
                self.logging.error(err_msg)
                raise Exception(err_msg)

            time.sleep(sleep_time)

        return vm

    def _create_bootstrap_vm_public_ip(self):
        self.logging.info("Creating bootstrap VM public IP")

        public_ip_parameters = {
            "location": self.azure_location,
            "public_ip_address_version": "IPV4"
        }
        return utils.retry_on_error()(
            self.network_client.public_ip_addresses.create_or_update)(
                self.cluster_name,
                self.bootstrap_vm_public_ip_name,
                public_ip_parameters).result()

    def _create_bootstrap_vm_secgroup(self):
        self.logging.info("Creating bootstrap VM security group")
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
                name="Allow_SSH")
        ]
        secgroup_params = net_models.NetworkSecurityGroup(
            name=self.bootstrap_vm_secgroup_name,
            location=self.azure_location,
            security_rules=secgroup_rules)

        return utils.retry_on_error()(
            self.network_client.network_security_groups.create_or_update)(
                self.cluster_name,
                self.bootstrap_vm_secgroup_name,
                secgroup_params).result()

    def _create_bootstrap_vm_nic(self):
        self.logging.info("Creating bootstrap VM NIC")

        public_ip = self._create_bootstrap_vm_public_ip()
        control_plane_subnet = utils.retry_on_error()(
            self.network_client.subnets.get)(
                self.cluster_name,
                "%s-vnet" % self.cluster_name,
                "%s-controlplane-subnet" % self.cluster_name)
        nsg = self._create_bootstrap_vm_secgroup()
        nic_parameters = {
            "location": self.azure_location,
            "network_security_group": {
                "id": nsg.id
            },
            "ip_configurations": [{
                "name": "%s-ipconfig" % self.bootstrap_vm_nic_name,
                "subnet": {
                    "id": control_plane_subnet.id
                },
                "public_ip_address": {
                    "id": public_ip.id
                }
            }]
        }
        return utils.retry_on_error()(
            self.network_client.network_interfaces.create_or_update)(
                self.cluster_name,
                self.bootstrap_vm_nic_name,
                nic_parameters).result()

    def _wait_for_ready_bootstrap_vm(self, timeout=600):
        self.logging.info("Waiting for bootstrap VM SSH port to be reachable")
        utils.wait_for_port_connectivity(self.bootstrap_vm_public_ip, 22)

        self.logging.info("Waiting up to %.2f minutes for bootstrap VM to "
                          "be ready", timeout / 60.0)
        cmd = [
            "ssh", "-o", "StrictHostKeyChecking=no", "-o",
            "UserKnownHostsFile=/dev/null", "-i", os.environ.get("SSH_KEY"),
            "capi@%s" % self.bootstrap_vm_public_ip,
            "'sudo bash -s' < %s" % os.path.join(
                os.getcwd(), "cluster-api/scripts/check-bootstrap-vm.sh")
        ]
        sleep_time = 10
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                err_msg = "Bootstrap VM was not ready within %.2f minutes" % (
                    timeout / 60)
                self.logging.error(err_msg)
                raise Exception(err_msg)

            stdout, _, ret = utils.run_cmd(
                cmd, stdout=True, shell=True, sensitive=True)

            if ret == 0:
                self.logging.info("Bootstrap VM is ready")
                break

            self.logging.warning(stdout.decode('ascii').strip())
            time.sleep(sleep_time)

    def _create_bootstrap_vm(self):
        self.logging.info("Setting up the bootstrap VM")

        cloud_config_file = os.path.join(
            os.getcwd(), "cluster-api/azure/bootstrap-vm-cloud-config.txt")
        with open(cloud_config_file) as f:
            cloud_config = f.read()
        vm_nic = self._create_bootstrap_vm_nic()
        vm_parameters = {
            "location": self.azure_location,
            "os_profile": {
                "computer_name": self.bootstrap_vm_name,
                "admin_username": "capi",
                "custom_data": base64.b64encode(
                    cloud_config.encode('ascii')).decode('ascii'),
                "linux_configuration": {
                    "disable_password_authentication": True,
                    "ssh": {
                        "public_keys": [{
                            "key_data": os.environ["AZURE_SSH_PUBLIC_KEY"],
                            "path": "/home/capi/.ssh/authorized_keys"
                        }]
                    }
                }
            },
            "hardware_profile": {
                "vm_size": self.bootstrap_vm_size
            },
            "storage_profile": {
                "image_reference": {
                    "publisher": "Canonical",
                    "offer": "UbuntuServer",
                    "sku": "18_04-lts-gen2",
                    "version": "latest"
                },
            },
            "network_profile": {
                "network_interfaces": [{
                    "id": vm_nic.id
                }]
            }
        }

        self.logging.info("Creating bootstrap VM")
        vm = utils.retry_on_error()(
            self.compute_client.virtual_machines.create_or_update)(
                self.cluster_name,
                self.bootstrap_vm_name,
                vm_parameters).result()
        vm = self._wait_for_bootstrap_vm()

        ip_config = self.network_client.network_interfaces.get(
            self.cluster_name, vm_nic.name).ip_configurations[0]
        self.bootstrap_vm_private_ip = ip_config.private_ip_address

        public_ip = self.network_client.public_ip_addresses.get(
            self.cluster_name, self.bootstrap_vm_public_ip_name)
        self.bootstrap_vm_public_ip = public_ip.ip_address

        self._wait_for_ready_bootstrap_vm()

        self.logging.info("Finished setting up the bootstrap VM")

        return vm

    def _cleanup_bootstrap_vm(self):
        self.logging.info("Cleaning up the bootstrap VM")

        self.logging.info("Deleting bootstrap VM")
        utils.retry_on_error()(self.compute_client.virtual_machines.delete)(
            self.cluster_name, self.bootstrap_vm_name).wait()

        self.logging.info("Deleting bootstrap VM NIC")
        utils.retry_on_error()(
            self.network_client.network_interfaces.delete)(
                self.cluster_name, self.bootstrap_vm_nic_name).wait()

        self.logging.info("Deleting bootstrap VM public IP")
        utils.retry_on_error()(self.network_client.public_ip_addresses.delete)(
            self.cluster_name, self.bootstrap_vm_public_ip_name).wait()

        self.logging.info("Deleting bootstrap VM security group")
        utils.retry_on_error()(
            self.network_client.network_security_groups.delete)(
                self.cluster_name, self.bootstrap_vm_secgroup_name).wait()

    @utils.retry_on_error()
    def _setup_bootstrap_vm(self):
        try:
            self._create_bootstrap_vm()
        except Exception as ex:
            self._cleanup_bootstrap_vm()
            raise ex

    def _wait_for_windows_agents(self, check_nodes_ready=True, timeout=3600):
        self.logging.info("Waiting up to %.2f minutes for the Windows agents",
                          timeout / 60.0)

        sleep_time = 5
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise Exception("The Windows agents didn't become ready "
                                "within %.2f minutes" % (timeout / 60.0))

            cmd = [
                self.kubectl, "get", "machine", "--kubeconfig",
                self.kind_kubeconfig_path,
                "--output=custom-columns=NAME:.metadata.name", "--no-headers"
            ]
            output, _ = utils.retry_on_error()(
                utils.run_shell_cmd)(cmd, sensitive=True)
            machines = output.decode().strip().split('\n')
            windows_machines = [
                # This value is given in the capz cluster.yaml config, and
                # it's hardcoded since it's going to be part of the Windows
                # agents hostnames, and together with the unique suffix added
                # by the cluster-api Azure provider, the length must be <= 15
                # characters.
                m for m in machines if m.startswith("capi-win-")
            ]
            if len(windows_machines) == 0:
                time.sleep(sleep_time)
                continue

            all_ready = True
            for windows_machine in windows_machines:
                cmd = [
                    self.kubectl, "get", "machine", "--kubeconfig",
                    self.kind_kubeconfig_path,
                    "--output=custom-columns=READY:.status.phase",
                    "--no-headers", windows_machine
                ]
                output, _ = utils.retry_on_error()(
                    utils.run_shell_cmd)(cmd, sensitive=True)
                status_phase = output.decode().strip()

                if status_phase != "Running":
                    all_ready = False
                    continue

                if not check_nodes_ready:
                    continue

                cmd = [
                    self.kubectl, "get", "machine", "--kubeconfig",
                    self.kind_kubeconfig_path,
                    "--output=custom-columns=NODE_NAME:.status.nodeRef.name",
                    windows_machine, "--no-headers"
                ]
                output, _ = utils.retry_on_error()(
                    utils.run_shell_cmd)(cmd, sensitive=True)
                node_name = output.decode("ascii").strip()

                all_ready = self._is_k8s_node_ready(node_name)

            if all_ready:
                self.logging.info("All the Windows agents are ready")
                break

            time.sleep(sleep_time)

    def _is_k8s_node_ready(self, node_name=None):
        if not node_name:
            self.logging.warning("Empty node_name parameter")
            return False

        cmd = [
            self.kubectl, "get", "--kubeconfig", self.capz_kubeconfig_path,
            "node", "-o", "yaml", node_name
        ]
        output, _ = utils.retry_on_error()(
            utils.run_shell_cmd)(cmd, sensitive=True)
        node = yaml.safe_load(output.decode('ascii'))

        if "status" not in node:
            self.logging.info("Node %s didn't report status yet", node_name)
            return False

        ready_condition = [
            c for c in node["status"]["conditions"] if c["type"] == "Ready"
        ]
        if len(ready_condition) == 0:
            self.logging.info("Node %s didn't report ready condition yet",
                              node_name)
            return False

        try:
            is_ready = strtobool(ready_condition[0]["status"])
        except ValueError:
            is_ready = False

        if not is_ready:
            self.logging.info("Node %s is not ready yet", node_name)
            return False

        return True

    def _create_capz_cluster(self):
        context = {
            "cluster_name": self.cluster_name,
            "cluster_network_subnet": self.cluster_network_subnet,
            "azure_location": self.azure_location,
            "azure_subscription_id": os.environ["AZURE_SUBSCRIPTION_ID"],
            "azure_tenant_id": os.environ["AZURE_TENANT_ID"],
            "azure_client_id": os.environ["AZURE_CLIENT_ID"],
            "azure_client_secret": os.environ["AZURE_CLIENT_SECRET"],
            "azure_ssh_public_key": os.environ["AZURE_SSH_PUBLIC_KEY"],
            "azure_ssh_public_key_b64": os.environ["AZURE_SSH_PUBLIC_KEY_B64"],
            "master_vm_size": self.master_vm_size,
            "win_minion_count": self.win_minion_count,
            "win_minion_size": self.win_minion_size,
            "win_minion_image_rg": self.win_minion_image_rg,
            "win_minion_image_gallery": self.win_minion_image_gallery,
            "win_minion_image_definition": self.win_minion_image_definition,
            "win_minion_image_version": self.win_minion_image_version,
            "ci_version": self.ci_version,
            "flannel_mode": self.flannel_mode,
            "container_runtime": self.container_runtime,
        }

        self.logging.info("Create CAPZ cluster")
        template_file = os.path.join(
            os.getcwd(), "cluster-api/azure/cluster.yaml.j2")
        output_file = "/tmp/capz-cluster.yaml"
        utils.render_template(template_file, output_file, context)
        utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "apply", "--kubeconfig", self.kind_kubeconfig_path,
            "-f", output_file
        ])
        self._wait_for_cluster()

        self._setup_bootstrap_vm()
        context["bootstrap_vm_address"] = self.bootstrap_vm_private_ip

        self.upload_to_bootstrap_vm("%s/" % self.ci_artifacts_dir)
        self.upload_to_bootstrap_vm(
            os.path.join(os.getcwd(), "cluster-api/scripts"))

        self.logging.info("Create CAPZ control-plane")
        template_file = os.path.join(
            os.getcwd(), "cluster-api/azure/control-plane.yaml.j2")
        output_file = "/tmp/control-plane.yaml"
        utils.render_template(template_file, output_file, context)
        utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "apply", "--kubeconfig", self.kind_kubeconfig_path,
            "-f", output_file
        ])

        self.logging.info("Create CAPZ Windows agents")
        template_file = os.path.join(
            os.getcwd(), "cluster-api/azure/windows-agents.yaml.j2")
        output_file = "/tmp/windows-agents.yaml"
        utils.render_template(template_file, output_file, context)
        utils.retry_on_error()(utils.run_shell_cmd)([
            self.kubectl, "apply", "--kubeconfig", self.kind_kubeconfig_path,
            "-f", output_file
        ])

    def _setup_capz_kubeconfig(self):
        self.logging.info("Setting up CAPZ kubeconfig")

        cmd = [
            self.kubectl, "get", "--kubeconfig", self.kind_kubeconfig_path,
            "secret/%s-kubeconfig" % self.cluster_name,
            "--output=custom-columns=KUBECONFIG_B64:.data.value",
            "--no-headers"
        ]
        output, _ = utils.retry_on_error()(utils.run_shell_cmd)(cmd)

        with open(self.capz_kubeconfig_path, 'w') as f:
            f.write(base64.b64decode(output).decode('ascii'))

    def _wait_for_cluster(self, timeout=900):
        self.logging.info(
            "Waiting up to %.2f minutes for the cluster to provision.",
            timeout / 60.0)

        sleep_time = 5
        start = time.time()
        cluster_resource_name = "cluster.cluster.x-k8s.io/%s" % (
            self.cluster_name)
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise Exception("Cluster didn't provision within %.2f "
                                "minutes" % (timeout / 60.0))

            cmd = [
                self.kubectl, "get", "cluster", "--kubeconfig",
                self.kind_kubeconfig_path, self.cluster_name,
                "--output=name"
            ]
            output, _ = utils.retry_on_error()(
                utils.run_shell_cmd)(cmd, sensitive=True)
            names = output.decode().strip().split('\n')
            found = [c for c in names if c == cluster_resource_name]
            if len(found) == 0:
                time.sleep(sleep_time)
                continue

            cmd = [
                self.kubectl, "get", "cluster", "--kubeconfig",
                self.kind_kubeconfig_path, self.cluster_name,
                "--output=custom-columns=CLUSTER_STATUS:.status.phase",
                "--no-headers"
            ]
            output, _ = utils.retry_on_error()(
                utils.run_shell_cmd)(cmd, sensitive=True)
            cluster_status = output.decode().strip()

            if cluster_status == "Provisioned":
                self.logging.info("Cluster provisioned in %.2f minutes",
                                  (time.time() - start) / 60.0)
                break

            time.sleep(sleep_time)

    def _wait_for_control_plane(self, timeout=2700):
        self.logging.info(
            "Waiting up to %.2f minutes for the control-plane to be ready.",
            timeout / 60.0)

        sleep_time = 5
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise Exception("The control-plane didn't become ready "
                                "within %.2f minutes" % (timeout / 60.0))

            cmd = [
                self.kubectl, "get", "machine", "--kubeconfig",
                self.kind_kubeconfig_path,
                "--output=custom-columns=NAME:.metadata.name", "--no-headers"
            ]
            output, _ = utils.retry_on_error()(
                utils.run_shell_cmd)(cmd, sensitive=True)
            machines = output.decode().strip().split('\n')
            control_plane_machines = [
                m for m in machines
                if m.startswith("%s-control-plane" % self.cluster_name)
            ]
            if len(control_plane_machines) == 0:
                time.sleep(sleep_time)
                continue

            all_ready = True
            for control_plane_machine in control_plane_machines:
                cmd = [
                    self.kubectl, "get", "machine", "--kubeconfig",
                    self.kind_kubeconfig_path,
                    "--output=custom-columns=READY:.status.phase",
                    "--no-headers", control_plane_machine
                ]
                output, _ = utils.retry_on_error()(
                    utils.run_shell_cmd)(cmd, sensitive=True)
                status_phase = output.decode().strip()

                if status_phase != "Running":
                    all_ready = False
                    continue

            if all_ready:
                self.logging.info(
                    "The control plane provisioned in "
                    "%.2f minutes", (time.time() - start) / 60.0)
                break

            time.sleep(sleep_time)

    def _create_kind_cluster(self):
        self.logging.info("Create Kind management cluster")
        kind_config_file = os.path.join(os.getcwd(),
                                        "cluster-api/kind-config.yaml")
        kind_node_image = (os.environ.get("KIND_NODE_IMAGE")
                           or "e2eteam/kind-node:v1.18.4")
        utils.run_shell_cmd([
            "kind", "create", "cluster", "--config", kind_config_file,
            "--kubeconfig", self.kind_kubeconfig_path, "--image",
            kind_node_image, "--wait", "15m"
        ])

        self.logging.info("Add the Azure cluster api components")
        capi_config = os.path.join(os.getcwd(),
                                   "cluster-api/azure/config.yaml")
        capi_version = "v0.3.8"
        capz_provider_version = "v0.4.6"
        utils.run_shell_cmd([
            "clusterctl", "init",
            "--kubeconfig", self.kind_kubeconfig_path,
            "--core", ("cluster-api:%s" % capi_version),
            "--bootstrap", ("kubeadm:%s" % capi_version),
            "--control-plane", ("kubeadm:%s" % capi_version),
            "--infrastructure", ("azure:%s" % capz_provider_version),
            "--config", capi_config
        ])

        self.logging.info("Wait for the deployments to be available")
        utils.run_shell_cmd([
            self.kubectl, "wait", "--kubeconfig", self.kind_kubeconfig_path,
            "--for=condition=Available", "--timeout", "5m", "deployments",
            "--all", "--all-namespaces"
        ])

    def _set_azure_variables(self):
        # Define the requried env variables list
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
                raise Exception("Env variable %s is not set" % env_var)
            os.environ[env_var] = os.environ.get(env_var).strip()
            b64_env_var = "%s_B64" % env_var
            os.environ[b64_env_var] = base64.b64encode(
                os.environ.get(env_var).encode('ascii')).decode('ascii')
        # Set Azure location if it's not set already
        if not self.azure_location:
            self.azure_location = random.choice(constants.AZURE_LOCATIONS)
