#!/bin/bash

log_msg() {
	echo "$(date -R) - $1"
}

log_msg "Starting backup..."

# Create backup folders
BACKUP_DIR=$(mktemp -d)
mkdir -p "${BACKUP_DIR}/configmaps"
mkdir -p "${BACKUP_DIR}/secrets"

# Backup configmaps
if [ -z "${BACKUP_CONFIGMAPS}" ]; then
	log_msg "BACKUP_CONFIGMAPS is empty. Not backing up any configmaps."
else
	for configmap in ${BACKUP_CONFIGMAPS//,/ }; do
		log_msg "Backing up configmap '${configmap}'..."
		kubectl get configmap "${configmap}" -o yaml > "${BACKUP_DIR}/configmaps/${configmap}.yaml"
	done
fi

# Backup secrets
if [ -z "${BACKUP_SECRETS}" ]; then
	log_msg "BACKUP_SECRETS is empty. Not backing up any secrets."
else
	for secret in ${BACKUP_SECRETS//,/ }; do
		log_msg "Backing up secret '${secret}'..."
		kubectl get secret "${secret}" -o yaml > "${BACKUP_DIR}/secrets/${secret}.yaml"
	done
fi

# Create backup archive
ARCHIVE_NAME="backup-$(date +%Y-%m-%d_%H-%M)"
log_msg "Creating archive '${ARCHIVE_NAME}.tar.gz'..."
tar -Pzcf "/tmp/${ARCHIVE_NAME}.tar.gz" "${BACKUP_DIR}"
rm -rf "${BACKUP_DIR}"

# Encrypt backup archive
if [ -z "${ENCRYPTION_KEY}" ]; then
	log_msg "ENCRYPTION_KEY is empty. Skipping archive encryption and upload..."
	exit
else
	log_msg "Encrypting archive /tmp/${ARCHIVE_NAME}.tar.gz..."
	# Create key
	openssl rand -out "/tmp/${ARCHIVE_NAME}.key" 32
	# Encrypt archive
	openssl enc -in "/tmp/${ARCHIVE_NAME}.tar.gz" -out "/tmp/${ARCHIVE_NAME}.tar.gz.enc" -pass file:"/tmp/${ARCHIVE_NAME}.key"

	# Encrypt key using public ssh key
	openssl rsautl -encrypt -pubin -inkey <(ssh-keygen -e -f "${ENCRYPTION_KEY}" -m PKCS8) \
		-in "/tmp/${ARCHIVE_NAME}.key" -out "/tmp/${ARCHIVE_NAME}.key.enc"

	rm "/tmp/${ARCHIVE_NAME}.tar.gz"
	rm "/tmp/${ARCHIVE_NAME}.key"
fi

# Upload backup archive
for file in "${ARCHIVE_NAME}.tar.gz.enc" "${ARCHIVE_NAME}.key.enc"; do
	log_msg "Uploading file ${file}..."
	az storage blob upload --container-name "${AZURE_STORAGE_CONTAINER_PROW_BKP}" \
		--account-key "${AZURE_STORAGE_ACCOUNT_KEY}" --file "/tmp/${file}" --name "${file}"
done

rm "/tmp/${ARCHIVE_NAME}.key.enc"
rm "/tmp/${ARCHIVE_NAME}.tar.gz.enc"
