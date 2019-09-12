# k8s-ci-runner

This tool is used by the sig-windows community to test K8s scenarios with Windows nodes. It deploys clusters in Azure and runs k8s e2e tests
agains those clusters.

How to use:

### Prerequisites

- terraform
- ansible
- golang > 1.12.4 ( needed to build tests and binaries )


### Environment requiurements

The tool requires the following env vars to be set in order to be able to deploy Azure clusters with terraform

### Basic run

```
civ2.py --ci=terraform-flannel --terraform-config --ssh-private-key-path=(defaults to $HOME/.ssh) --ssh-public-key-path=(defaults to $HOME/.ssh) \
        --test=True --up=True --down=True --build=k8sbins --rg_name=test-rg --ansibleRepo=ansible_repo_to_deploy_k8s --ansibleBranch=ansible_branch \
        --test-focus-regex --test-skip-regex
```

### Full parameter list

 ```
 
  --repo-list REPO_LIST
                        Repo list with registries for test images. (default:
                        https://raw.githubusercontent.com/kubernetes-sigs
                        /windows-testing/master/images/image-repo-list)
  --parallel-test-nodes PARALLEL_TEST_NODES
  --test-dry-run TEST_DRY_RUN
  --test-focus-regex TEST_FOCUS_REGEX
  --test-skip-regex TEST_SKIP_REGEX
  --kubetest-link KUBETEST_LINK
  
  --location LOCATION   Resource group location. (default: eastus)
  --rg_name RG_NAME     resource group name. (default: None)
  --master-vm-name MASTER_VM_NAME
                        Name of master vm. (default: None)
  --master-vm-size MASTER_VM_SIZE
                        Size of master vm (default: Standard_D2s_v3)
  --win-minion-count WIN_MINION_COUNT
                        Number of windows minions for the deployment.
                        (default: 2)
  --win-minion-name-prefix WIN_MINION_NAME_PREFIX
                        Prefix for win minion vm names. (default: winvm)
  --win-minion-size WIN_MINION_SIZE
                        Size of minion vm (default: Standard_D2s_v3)
  --terraform-config TERRAFORM_CONFIG
  --ssh-public-key-path SSH_PUBLIC_KEY_PATH
  --ssh-private-key-path SSH_PRIVATE_KEY_PATH
  --ansibleRepo ANSIBLEREPO
                        Ansible Repository for ovn-ovs playbooks. (default:
                        http://github.com/e2e-win/flannel-kubernetes)
  --ansibleBranch ANSIBLEBRANCH
                        Ansible Repository branch for ovn-ovs playbooks.
                        (default: master)
  --flannelMode FLANNELMODE
                        Option: overlay or host-gw (default: overlay)
  --containerRuntime CONTAINERRUNTIME
                        Container runtime to set in ansible: docker /
                        containerd. (default: docker)
  --remoteCmdRetries REMOTECMDRETRIES
                        Number of retries Ansible adhoc command should do.
                        (default: 5)
  -c CONFIGFILE, --configfile CONFIGFILE
                        Config file path. (default: None)
  --up UP               Deploy test cluster. (default: False)
  --down DOWN           Destroy cluster on finish. (default: False)
  --build BUILD         Build k8s binaries. Values: k8sbins, containerdbins,
                        sdnbins (default: None)
  --test TEST           Run tests. (default: False)
  --admin-openrc ADMIN_OPENRC
                        Openrc file for OpenStack cluster (default: False)
  --log-path LOG_PATH   Path to place all artifacts (default: /tmp/civ2_logs)
  --ci CI               OVN-OVS, Flannel (default: None)
  --cluster-name CLUSTER_NAME
                        Name of cluster. (default: None)
  --k8s-repo K8S_REPO
  --k8s-branch K8S_BRANCH
  --containerd-repo CONTAINERD_REPO
  --containerd-branch CONTAINERD_BRANCH
  --sdn-repo SDN_REPO
  --sdn-branch SDN_BRANCH
  --hold HOLD           Useful for debugging while running in containerd.
                        Sleeps the process after setting the env for testing
                        so user can manually exec from container. (default:
                        False)
                        ```



  
