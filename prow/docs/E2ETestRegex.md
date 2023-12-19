# E2E Test Regex

Currently, the `k8s-e2e-runner` uses E2E focus / skip regular expressions
stored as YAML files into [prow/test-regex](../test-regex) directory.

Each file in the directory adheres to the following format:

```yaml
focus: "<focus-regex>"
skip: "<skip-regex>"
```

The `focus` and `skip` regular expressions filter the E2E tests executed by
the `k8s-e2e-runner`.

The `e2e-runner` tool accepts `--test-regex-file-url` CLI argument, specifying
the URL of the YAML file containing the E2E focus/skip regular expressions.

In the current [sig-windows-networking.yaml](../jobs/sig-windows-networking.yaml)
jobs file, we pass the direct GitHub URL of the YAML file from the
[e2e-win/k8s-e2e-runner](https://github.com/e2e-win/k8s-e2e-runner) repository.

For instance, the [capz_flannel.yaml](../test-regex/capz_flannel.yaml) test regex
file is passed to the `e2e-runner` like this:

```bash
--test-regex-file-url=https://raw.githubusercontent.com/e2e-win/k8s-e2e-runner/main/prow/test-regex/capz_flannel.yaml
```

## Building E2E Focus / Skip Regular Expressions

Before delving into the construction of `focus` / `skip` regular expressions,
it's essential to understand that these expressions filter tests by their full
names, which include various labels.

Consider the following example of an E2E test full name:

```shell
[sig-windows] [Feature:WindowsHostProcessContainers] [MinimumKubeletVersion:1.22] HostProcess containers should run as a process on the host/node
```

All E2E test full names are prefixed with a label corresponding to the E2E test
suite, such as `[sig-windows]` in this case.

Each test suite is organized in subdirectories in the upstream Kuberetes
[test/e2e](https://github.com/kubernetes/kubernetes/tree/master/test/e2e) directory.

To determine the E2E test suite of a test from the code, search for all
occurrences of the `framework.SIGDescribe` function call, which registers the
E2E test suite. You can use [this search query](https://github.com/search?q=repo%3Akubernetes%2Fkubernetes+framework.SIGDescribe+path%3A%2F%5Etest%5C%2Fe2e%5C%2F%2F&type=code)
in the upstream Kubernetes repository.

In addition to the test suite label, the test full name contains labels
corresponding to the test features or requirements. For example,
`[Feature:WindowsHostProcessContainers]` and `[MinimumKubeletVersion:1.22]`
indicate that the test is meant for Windows nodes (capable to run host process
containers) and requires a minimum Kubelet version of 1.22.

Occasionally, you may encounter a `[LinuxOnly]` label, specifying that the test
is meant for Linux nodes only.

### CAPZ Flannel E2E Tests

Let's examine the current [capz_flannel.yaml](../test-regex/capz_flannel.yaml) test regex file:

```yaml
focus: "\\[Conformance\\]|\\[NodeConformance\\]|\\[sig-windows\\]"
skip: "\\[LinuxOnly\\]|\\[Serial\\]|\\[Slow\\]|\\[Feature\\:GPUDevicePlugin\\]|\\[sig-api-machinery\\].Garbage.collector"
```

The `focus` regular expression matches E2E tests full names containing at least
one of the following labels:

* `[Conformance]` or `[NodeConformance]`, tests marked with these are part of
  the upstream [Kubernetes conformance testing](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/conformance-tests.md#conformance-testing-in-kubernetes)
  suite, defining the core set of interoperable features for conformant
  Kubernetes clusters.
* `[sig-windows]`: Windows-only tests.

From the list of matched `focus` E2E tests, the `skip` regular expression
filters out tests containing at least one of the following labels:

* `[LinuxOnly]`: Linux-only tests.
* `[Serial]`: Non-parallelizable tests.
* `[Slow]`: Slow tests, unsuitable for parallel test runners used in the
  CAPZ Flannel CI jobs.
* `[Feature:GPUDevicePlugin]`, GPU device plugin tests, irrelevant for CI jobs
  without GPU-enabled Azure machines.
* `[sig-api-machinery].Garbage.collector`: Matches all tests from the
  `[sig-api-machinery]` test suite starting with `Garbage collector`.
  These tests cause disruptions on Windows, so they are skipped. There's an
  ongoing discussion [here](https://github.com/kubernetes/kubernetes/issues/107394),
  and some CI/CD systems [run these tests serially](https://github.com/kubernetes-sigs/cluster-api-provider-azure/pull/1953) as a workaround.

### AKS E2E Tests

The AKS E2E tests are defined in the [aks.yaml](../test-regex/aks.yaml) test file as:

```yaml
focus: "\\[Conformance\\]|\\[NodeConformance\\]|\\[sig-windows\\]|\\[sig-network\\].Networking.Granular.Checks|\\[sig-network\\].LoadBalancers"
skip: "\\[LinuxOnly\\]|\\[Serial\\]|\\[Feature\\:GPUDevicePlugin\\]|\\[Feature\\:SCTPConnectivity\\]|\\[Disruptive\\]|should.function.for.service.endpoints.using.hostNetwork|\\[sig-api-machinery\\]|\\[sig-cli\\]|\\[sig-auth\\]|\\[sig-apps\\].*\\[Slow\\]|\\[sig-node\\].*\\[Slow\\]"
```

Comparing the AKS E2E tests with the CAPZ Flannel E2E tests, the AKS E2E tests
match more networking-specific tests via the `focus` regular expression
intentionally, as this is the objective of the AKS CI jobs.

However, the `skip` regular expression is also more restrictive, as we want to
skip tests that are not networking-related or are not compatible with Windows.

In addition to the tests run by the CAPZ Flannel CI, the AKS CI also include
tests labeled with `[sig-network].Networking.Granular.Checks` or `[sig-network].LoadBalancers`.
These tests are a subset of the `sig-network` suite, which contains all tests
related to networking.

In the beginning, the `sig-network` suite was mostly Linux-specific, but
efforts are underway in the upstream Kubernetes community to make the tests
Windows-compatible.

Initially, we enabled only the tests labeled with
`[sig-network].Networking.Granular.Checks` or `[sig-network].LoadBalancers`.
Adjustments to the skip regular expression were made to exclude tests not
compatible with Windows from the matched sig-network tests.
