#!/bin/bash
set -e

E2E_RUNNER_REPO="${K8S_E2E_RUNNER_REPO:-https://github.com/e2e-win/k8s-e2e-runner.git}"
E2E_RUNNER_BRANCH="${K8S_E2E_RUNNER_BRANCH:-master}"

pip3 install "git+${E2E_RUNNER_REPO}@${E2E_RUNNER_BRANCH}#egg=e2e-runner&subdirectory=e2e-runner"

e2e-runner run ci --quiet --artifacts-directory=${ARTIFACTS} "$@"
