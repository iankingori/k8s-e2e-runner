#!/usr/bin/env bash
set -e

DIR=$(dirname $0)

if [[ -z $AZURE_SUBSCRIPTION_ID ]]; then echo "AZURE_SUBSCRIPTION_ID is not set"; exit 1; fi
if [[ -z $AZURE_TENANT_ID ]]; then echo "AZURE_TENANT_ID is not set"; exit 1; fi
if [[ -z $AZURE_CLIENT_ID ]]; then echo "AZURE_CLIENT_ID is not set"; exit 1; fi
if [[ -z $AZURE_CLIENT_SECRET ]]; then echo "AZURE_CLIENT_SECRET is not set"; exit 1; fi

mkdir -p $DIR/.env/ssh
ssh-keygen -N "" -C "" -f $DIR/.env/ssh/id_rsa

mkdir -p $DIR/.env/docker-creds
if [[ -e $DOCKER_CONFIG_FILE ]]; then
    touch $DIR/.env/docker-creds/config.json
    chmod 600 $DIR/.env/docker-creds/config.json
    cp $DOCKER_CONFIG_FILE $DIR/.env/docker-creds/config.json
fi

touch $DIR/.env/env.sh
chmod 600 $DIR/.env/env.sh

echo "AZURE_SUBSCRIPTION_ID=$AZURE_SUBSCRIPTION_ID" >> $DIR/.env/env.sh
echo "AZURE_TENANT_ID=$AZURE_TENANT_ID" >> $DIR/.env/env.sh
echo "AZURE_CLIENT_ID=$AZURE_CLIENT_ID" >> $DIR/.env/env.sh
echo "AZURE_CLIENT_SECRET=$AZURE_CLIENT_SECRET" >> $DIR/.env/env.sh

echo "SSH_PRIVATE_KEY_PATH=/root/.ssh/id_rsa" >> $DIR/.env/env.sh
echo "SSH_PUBLIC_KEY_PATH=/root/.ssh/id_rsa.pub" >> $DIR/.env/env.sh
