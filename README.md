# K8s E2E Runner

This repository contains the following:

* `e2e-runner`

    This tool is used by the sig-windows community to test K8s scenarios with Windows nodes. It deploys clusters in Azure and runs the K8s E2E tests against those clusters.

    In order to use the runner, you must have the prerequisites installed. There is a public Docker image with the runner environment already prepared.

    If you want to quickly use the runner, make sure you have Docker installed, and run these:

    ```
    docker run --rm --entrypoint bash -it e2eteam/k8s-e2e-runner:latest

    pip3 install git+https://github.com/e2e-win/k8s-e2e-runner.git#egg=e2e-runner&subdirectory=e2e-runner
    ```

    At this point, the runner CI can be executed via `e2e-runner run ci` and customize the job run via parameters. The full list of supported parameters can be found by running:
    ```
    e2e-runner run ci --help
    ```

* `image-builder`, contains the scripts needed to build custom K8s Windows worker images.

* `tools/kube-backup`, used to periodically backup the existing prow environment, and push it into an Azure storage account.
