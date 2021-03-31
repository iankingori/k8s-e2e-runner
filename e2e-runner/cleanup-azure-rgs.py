#!/usr/bin/env python3

import logging
import os

from datetime import datetime

import configargparse

from azure.identity import ClientSecretCredential
from azure.mgmt.resource import ResourceManagementClient


logger = logging.getLogger("cleanup-azure-rgs")


def setup_logging():
    level = logging.DEBUG
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )
    stream = logging.StreamHandler()
    stream.setLevel(level)
    stream.setFormatter(formatter)
    logger.addHandler(stream)


def parse_args():
    p = configargparse.get_argument_parser(
        name="Azure resource groups cleanup script.")
    p.add("--filter-tag-name", type=str,
          default="ciName",
          help="The filter tag name used when listing the resource groups.")
    p.add("--filter-tag-value", type=str,
          default="k8s-sig-win-networking-prow-flannel-e2e",
          help="The filter tag value used when listing the resource groups.")
    p.add("--max-age-minutes", type=int,
          default=720,
          help="The maximum allowed age of an Azure resource group (given in "
          "minutes). If the resource group is older than this, then it's "
          "deleted. To find out the age of a resource group, the tag "
          "'creationTimestamp' is used.")
    return p.parse_known_args()


def get_azure_credentials():
    required_env_vars = [
        "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID",
        "AZURE_SUB_ID"
    ]
    for env_var in required_env_vars:
        if not os.environ.get(env_var):
            raise ValueError("Env variable %s is not set" % env_var)
    credentials = ClientSecretCredential(
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
        tenant_id=os.environ["AZURE_TENANT_ID"])
    subscription_id = os.environ["AZURE_SUB_ID"]
    return credentials, subscription_id


def main():
    setup_logging()
    args = parse_args()[0]

    credentials, subscription_id = get_azure_credentials()
    client = ResourceManagementClient(credentials, subscription_id)

    filter = "tagName eq '{}' and tagValue eq '{}'".format(
        args.filter_tag_name, args.filter_tag_value)
    logger.info("Listing resource groups filtered by the given tag.")
    for rg in client.resource_groups.list(filter=filter):
        logger.info("Found resource group: %s.", rg.name)

        creation_timestamp = rg.tags.get('creationTimestamp')
        if not creation_timestamp:
            logger.warning("The resource group doesn't have the creation "
                           "timestamp tag. Skipping it.")
            continue

        creation_date = datetime.fromisoformat(creation_timestamp)
        now_date = datetime.fromisoformat(datetime.utcnow().isoformat())
        age_minutes = (now_date - creation_date).seconds / 60

        if age_minutes > args.max_age_minutes:
            logger.info("Deleting the resource group.")
            client.resource_groups.begin_delete(rg.name)
        else:
            logger.info(
                "Resource group age (%s minutes) is not bigger than "
                "maximum allowed age (%s minutes).", age_minutes,
                args.max_age_minutes)


if __name__ == "__main__":
    main()
