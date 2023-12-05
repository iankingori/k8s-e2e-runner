# Prow on AKS Access

In order to access the AKS cluster with the Prow system, you need access to the Azure subscription where the AKS cluster is deployed.

The following steps assume that:

* The [az CLI tool](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli#install) is installed and configured with the Azure subscription where the AKS cluster is deployed.
* The [kubectl CLI tool](https://kubernetes.io/docs/tasks/tools/#kubectl) is installed.

To get the AKS cluster kubeconfig, run the following:

```bash
AKS_CLUSTER_RG="k8s-sig-windows-networking"
AKS_CLUSTER_NAME="sig-win-networking-prow"
KUBECONFIG_PATH="$HOME/.kube/sig-win-networking-prow-kubeconfig.yaml"

az aks get-credentials -g $AKS_CLUSTER_RG --name $AKS_CLUSTER_NAME -f $KUBECONFIG_PATH
```

Validate that kubeconfig works by running:

```bash
export KUBECONFIG="$HOME/.kube/sig-win-networking-prow-kubeconfig.yaml"

kubectl get nodes
```

You should see the AKS cluster nodes:

```shell
NAME                                STATUS   ROLES   AGE   VERSION
aks-nodepool1-15622114-vmss000000   Ready    agent   25h   v1.28.3
aks-nodepool1-15622114-vmss000001   Ready    agent   25h   v1.28.3
```
