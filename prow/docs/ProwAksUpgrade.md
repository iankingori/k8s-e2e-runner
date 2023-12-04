# Prow on AKS Upgrade

## Upgrade AKS cluster

Check if the AKS cluster has any upgrades available:

```bash
$ az aks get-upgrades -g k8s-sig-windows-networking -n sig-win-networking-prow -o table
Name     ResourceGroup               MasterVersion    Upgrades
-------  --------------------------  ---------------  --------------
default  k8s-sig-windows-networking  1.27.7           1.28.0, 1.28.3
```

For example, the above AKS cluster is deployed with version `1.27.7` and has two upgrades available: `1.28.0` and `1.28.3`.

Upgrade the AKS cluster to the latest upgrade version available:

```bash
az aks upgrade -g k8s-sig-windows-networking -n sig-win-networking-prow --kubernetes-version 1.28.3
```

NOTE: You can only upgrade one major version at a time. For example, if your cluster is running version 1.27, you can upgrade to 1.28, but not to 1.29 or later. The upgrade to 1.29 (or later) requires two steps: 1.27 -> 1.28, then 1.28 -> 1.29.

## Upgrade Prow

The [prow/cluster.yaml](https://github.com/e2e-win/k8s-e2e-runner/blob/main/prow/cluster.yaml) file contains the full Prow deployment used. This is derived from the upstream [prow/starter-gcs.yaml](https://github.com/kubernetes/test-infra/blob/master/config/prow/cluster/starter/starter-gcs.yaml) file, since we also use a GCS bucket to publish Prowjobs artifacts.

When a Prow upgrade is needed, we need to compare [prow/cluster.yaml](https://github.com/e2e-win/k8s-e2e-runner/blob/main/prow/cluster.yaml) with the upstream [prow/starter-gcs.yaml](https://github.com/kubernetes/test-infra/blob/master/config/prow/cluster/starter/starter-gcs.yaml) file. Unless there are major changes to the Prow components, we only need to update the image version tags in:

* [prow/cluster.yaml](https://github.com/e2e-win/k8s-e2e-runner/blob/main/prow/cluster.yaml), for all the Prow components.
* [prow/config.yaml](https://github.com/e2e-win/k8s-e2e-runner/blob/main/prow/config.yaml), for the `utility_images`.

Keep in mind that the existing AKS Prow deployment uses:

* A minimal `config.yaml` saved in the `config` configmap.
* A minimal `plugins.yaml` saved in the `plugins` configmap.
* A separate `job-config` configmap with the periodic jobs, populated from [prow/jobs/sig-windows-networking.yaml](https://github.com/e2e-win/k8s-e2e-runner/blob/main/prow/jobs/sig-windows-networking.yaml) file.
* Traefik ingress controller instead of Nginx ingress controller (so different annotations are given to the Prow `Ingress` resource).

These are all the specific differences of the AKS Prow [cluster.yaml](https://github.com/e2e-win/k8s-e2e-runner/blob/main/prow/cluster.yaml) compared to the upstream [prow/starter-gcs.yaml](https://github.com/kubernetes/test-infra/blob/master/config/prow/cluster/starter/starter-gcs.yaml) deployment.

After the changes are made, we need to apply them via:

```bash
# change directory to "prow" directory of the local k8s-e2e-runner repo clone.
cd <path-to-k8s-e2e-runner>/prow

# update the Prow Kubernetes cluster.
kubectl apply -f cluster.yaml

# update the main Prow configmap.
make update-prow-config
```

For example, [this](https://github.com/e2e-win/k8s-e2e-runner/commit/d6de5f8f9385f9eeee4a948e8e428afd0aa0e40c) is a commit that merely updates the images tags, because no other changes were needed.
