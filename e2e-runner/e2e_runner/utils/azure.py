import os
from datetime import datetime

import tenacity
from e2e_runner import constants as e2e_constants
from e2e_runner import logger as e2e_logger
from e2e_runner.utils import utils as e2e_utils

from azure.core import exceptions as azure_exceptions
from azure.identity import ClientSecretCredential
from azure.mgmt.resource.resources import models as resources_models

logging = e2e_logger.get_logger(__name__)


def get_credentials():
    e2e_utils.validate_non_empty_env_variables([
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
    ])
    credentials = ClientSecretCredential(
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
        tenant_id=os.environ["AZURE_TENANT_ID"])
    subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
    return credentials, subscription_id


def get_least_used_location(compute_client, network_client):
    def get_usages(usages_list_func, usage_names):
        usages = {}
        for location in e2e_constants.AZURE_LOCATIONS:
            max_usage = 0
            usages_list = e2e_utils.retry_on_error()(
                usages_list_func)(location=location)
            for i in usages_list:
                if i.name.value in usage_names:
                    usage = i.current_value / i.limit
                    if usage > max_usage:
                        max_usage = usage
            usages[location] = max_usage
        return e2e_utils.sort_dict_by_value(usages)

    logging.info("Determining the least used Azure location")
    compute_usages = get_usages(
        usages_list_func=compute_client.usage.list,
        usage_names=e2e_constants.COMPUTE_QUOTAS)
    network_usages = get_usages(
        usages_list_func=network_client.usages.list,
        usage_names=e2e_constants.NETWORK_QUOTAS)
    usages = {}
    for loc in e2e_constants.AZURE_LOCATIONS:
        if compute_usages[loc] > network_usages[loc]:
            usages[loc] = compute_usages[loc]
        else:
            usages[loc] = network_usages[loc]
    usages = e2e_utils.sort_dict_by_value(usages)
    return next(iter(usages))


def delete_resource_group(client, resource_group_name, wait=True):
    logging.info("Deleting resource group %s", resource_group_name)
    try:
        delete_async_operation = e2e_utils.retry_on_error()(
            client.resource_groups.begin_delete)(resource_group_name)
        if wait:
            delete_async_operation.wait()
    except azure_exceptions.ResourceNotFoundError as e:
        if e.error.code == "ResourceGroupNotFound":  # pyright: ignore
            logging.warning(
                "Resource group %s does not exist", resource_group_name)
        else:
            raise e


def create_resource_group(client, name, location, tags):
    logging.info("Creating resource group %s", name)
    rg_params = resources_models.ResourceGroup(location=location, tags=tags)
    client.resource_groups.create_or_update(name, rg_params)
    for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_delay(600),  # pyright: ignore
            wait=tenacity.wait_exponential(max=30),  # pyright: ignore
            retry=tenacity.retry_if_exception_type(AssertionError),  # pyright: ignore # noqa:
            reraise=True):
        with attempt:
            rg = e2e_utils.retry_on_error()(client.resource_groups.get)(name)
            assert rg.properties.provisioning_state == "Succeeded"


def get_resource_group_tags():
    tags = {
        'creationTimestamp': datetime.utcnow().isoformat(),
        'ciName': 'k8s-sig-win-networking-prow-flannel-e2e',
        'DO-NOT-DELETE': 'RG spawned by the k8s-sig-win-networking CI',
    }
    build_id = os.environ.get('BUILD_ID')
    if build_id:
        tags['buildID'] = build_id
    job_name = os.environ.get('JOB_NAME')
    if job_name:
        tags['jobName'] = job_name
    return tags
