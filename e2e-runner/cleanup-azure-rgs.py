#!/usr/bin/env python3

import logging
import json
import os

from datetime import datetime

import configargparse
import sh

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
    p.add("--dry-run", action="store_true",
          help="Flag to be used when testing.")
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
        os.environ[env_var] = os.environ.get(env_var).strip()
    credentials = ClientSecretCredential(
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
        tenant_id=os.environ["AZURE_TENANT_ID"])
    subscription_id = os.environ["AZURE_SUB_ID"]
    return credentials, subscription_id


def is_prowjob_finished(build_id):
    if not build_id:
        logger.warning("The resource group doesn't have the build id tag.")
        return False
    output = sh.kubectl('get', 'prowjob', '-n', 'default', '-o', 'json',
                        '-l', 'prow.k8s.io/build-id={}'.format(build_id))
    prowjob = json.loads(output.stdout)
    if len(prowjob['items']) == 0:
        logger.info("The prowjob doesn't exist anymore.")
        return True
    state = prowjob['items'][0]['status'].get('state')
    if state != 'pending':
        logger.info("The prowjob is not running anymore.")
        return True
    return False


def is_rg_older(creation_timestamp_tag, max_age_minutes):
    if not creation_timestamp_tag:
        logger.warning("The resource group doesn't have the creation "
                       "timestamp tag.")
        return False
    creation_date = datetime.fromisoformat(creation_timestamp_tag)
    now_date = datetime.fromisoformat(datetime.utcnow().isoformat())
    age_minutes = (now_date - creation_date).seconds / 60
    if age_minutes > max_age_minutes:
        logger.info("Resource group is older than the max allowed age.")
        return True
    logger.info(
        "Resource group age (%s minutes) is not bigger than "
        "maximum allowed age (%s minutes).", age_minutes, max_age_minutes)
    return False


def delete_resource_group(client, rg_name, dry_run=False):
    if not dry_run:
        logger.info('Deleting the resource group "%s".', rg_name)
        client.resource_groups.begin_delete(rg_name)
    else:
        logger.info('Dry-run: The resource group "%s" would be deleted.',
                    rg_name)


def main():
    setup_logging()
    args = parse_args()[0]

    credentials, subscription_id = get_azure_credentials()
    client = ResourceManagementClient(credentials, subscription_id)

    filter = "tagName eq '{}' and tagValue eq '{}'".format(
        args.filter_tag_name, args.filter_tag_value)
    logger.info("Listing Prow Azure resource groups.")
    for rg in client.resource_groups.list(filter=filter):
        logger.info('Found resource group "%s".', rg.name)

        if is_prowjob_finished(rg.tags.get('buildID')):
            delete_resource_group(client, rg.name, args.dry_run)
            continue

        if is_rg_older(rg.tags.get('creationTimestamp'), args.max_age_minutes):
            delete_resource_group(client, rg.name, args.dry_run)
            continue


if __name__ == "__main__":
    main()
