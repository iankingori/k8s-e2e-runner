#!/bin/bash

BACKUP_DIR=$(mktemp -d)
ARCHIVE_NAME="backup-$(date +%Y-%m-%d_%H-%M).tar.gz"

log_msg() {
	echo "$(date -R) - $1"
}

log_msg "Starting backup..."

mkdir -p "${BACKUP_DIR}/configmaps"
mkdir -p "${BACKUP_DIR}/secrets"

if [ -z "${BACKUP_CONFIGMAPS}" ]; then
	log_msg "BACKUP_CONFIGMAPS is empty. Not backing up any configmaps."
else
	for configmap in ${BACKUP_CONFIGMAPS//,/ }; do
		log_msg "Backing up configmap '${configmap}'..."
		kubectl get configmap "${configmap}" -o yaml > "${BACKUP_DIR}/configmaps/${configmap}.yaml"
	done
fi

if [ -z "${BACKUP_SECRETS}" ]; then
	log_msg "BACKUP_SECRETS is empty. Not backing up any secrets."
else
	for secret in ${BACKUP_SECRETS//,/ }; do
		log_msg "Backing up secret '${secret}'..."
		kubectl get secret "${secret}" -o yaml > "${BACKUP_DIR}/secrets/${secret}.yaml"
	done
fi

log_msg "Creating archive '${ARCHIVE_NAME}'..."
tar -zcf "/tmp/${ARCHIVE_NAME}" "${BACKUP_DIR}"
rm -rf "${BACKUP_DIR}"

# TODO: Upload archive "/tmp/${ARCHIVE_NAME}"

