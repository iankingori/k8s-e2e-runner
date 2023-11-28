# Manual Prowjob Trigger

In order to manually trigger a Prowjob, we need:

* [golang](https://go.dev/doc/install) tool installed.
* [kubectl](https://kubernetes.io/docs/tasks/tools) tool installed.
* `KUBECONFIG` environment variable set, for the Kubernetes cluster where the Prow system is running.

After golang is installed make sure that `$GOPATH/bin` is in your `$PATH` environment variable (more info about `$GOPATH`
[here](https://pkg.go.dev/cmd/go#hdr-GOPATH_environment_variable)).

Once golang is configured, we need to install the following tools:

```bash
go install k8s.io/test-infra/prow/cmd/mkpj@latest
go install github.com/mikefarah/yq/v4@v4.40.3
```

With the required tools installed, change directory to the [k8s-e2e-runner](../../) local cloned repo, and run the following to trigger a particular Prowjob:

```bash
JOB_NAME="aks-e2e-ltsc2022-azurecni-1.27"

mkpj --job=${JOB_NAME} \
    --job-config-path=./prow/jobs/sig-windows-networking.yaml \
    --config-path=./prow/config.yaml | \
        yq '.metadata.namespace = "prow"' | kubectl apply -f -
```

NOTE: The above code snippet assumes that Prow system watches `Prowjob` resources from the `prow` Kubernetes namespace.

In order to check the available Prowjobs, check the [sig-windows-networking.yaml](../../prow/jobs/sig-windows-networking.yaml) file.
