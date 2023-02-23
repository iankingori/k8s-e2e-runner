import base64
import math
import os
import time

import pendulum
import tenacity
from e2e_runner import exceptions as e2e_exceptions
from e2e_runner import logger as e2e_logger
from kubernetes import client, config, utils, watch

logging = e2e_logger.get_logger(__name__)


class KubernetesClient(object):

    def __init__(self, config_file=None):
        config.load_kube_config(config_file=config_file)
        self.core_v1_api = client.CoreV1Api()
        self.api_client = client.ApiClient()

    def watch_pod_log(self, name, namespace="default"):
        w = watch.Watch()
        read_logs_since_sec = None
        last_log_time = None
        while True:
            try:
                logs = w.stream(
                    self.core_v1_api.read_namespaced_pod_log,
                    name=name,
                    namespace=namespace,
                    timestamps=True,
                    since_seconds=read_logs_since_sec,
                )
                for line in logs:
                    timestamp, message = self._parse_log_line(line)
                    print(message)
                    if timestamp:
                        last_log_time = timestamp

                time.sleep(10)

                if not self.is_pod_running(name, namespace):
                    break

            except Exception as e:
                logging.warning("Failed to read logs for pod %s: %s", name, e)

            logging.warning("Pod %s log read interrupted. Resuming...", name)
            if last_log_time:
                delta = (pendulum.now(tz="UTC") -
                         pendulum.parse(last_log_time, tz="UTC"))  # pyright: ignore # noqa:
                read_logs_since_sec = math.ceil(delta.total_seconds())  # pyright: ignore # noqa:

    def get_pod(self, name, namespace="default"):
        return self.core_v1_api.read_namespaced_pod(name, namespace)

    def is_pod_running(self, name, namespace="default"):
        return self.get_pod_phase(name, namespace) == "Running"

    def wait_running_pods(self, name=None, namespace="default", timeout=600):
        pods = []
        if name is not None:
            pods.append(self.get_pod(name, namespace))
        else:
            pods = self.core_v1_api.list_pod_for_all_namespaces().items
        logging.info(
            "Waiting up to %.2f minutes for given pod(s) to be ready",
            timeout / 60.0)
        kwargs = {
            "stop": tenacity.stop_after_delay(timeout),  # pyright: ignore
            "wait": tenacity.wait_exponential(max=10),  # pyright: ignore
            "retry": tenacity.retry_if_exception_type(AssertionError),  # pyright: ignore # noqa:
            "reraise": True,
        }
        for attempt in tenacity.Retrying(**kwargs):
            with attempt:
                pods_not_running = []
                for pod in pods:
                    pod_name = pod.metadata.name
                    pod_namespace = pod.metadata.namespace
                    if not self.is_pod_running(pod_name, pod_namespace):
                        pods_not_running.append(f"{pod_namespace}/{pod_name}")
                assert len(pods_not_running) == 0, (
                    "The following pods are not running yet: {}".format(
                        ', '.join(pods_not_running)
                    )
                )

    def get_pod_phase(self, name, namespace="default"):
        pod = self.get_pod(name, namespace)
        return pod.status.phase  # pyright: ignore

    def get_pod_container_status(self, pod_name, container_name,
                                 namespace="default"):
        pod = self.get_pod(pod_name, namespace)
        container_statuses = [
            c_status for c_status in pod.status.container_statuses
            if c_status.name == container_name
        ]
        if len(container_statuses) == 0:
            raise e2e_exceptions.PodContainerStatusNotFound(
                f"Pod({pod_name}) container({container_name}) "
                "status not found")
        return container_statuses[0]

    def wait_pod_phase(self, name, wanted_phase, namespace="default",
                       timeout=300):
        logging.info("Waiting for pod %s to reach status phase %s",
                     name, wanted_phase)
        kwargs = {
            "stop": tenacity.stop_after_delay(timeout),  # pyright: ignore
            "wait": tenacity.wait_exponential(max=10),  # pyright: ignore
            "retry": tenacity.retry_if_exception_type(AssertionError),  # pyright: ignore # noqa:
            "reraise": True,
        }
        for attempt in tenacity.Retrying(**kwargs):
            with attempt:
                phase = self.get_pod_phase(name, namespace)
                assert phase == wanted_phase, (
                    f"Pod {name} status phase {phase} is not the wanted "
                    f"status phase {wanted_phase}")

    def wait_running_pod(self, name, namespace="default", timeout=300):
        self.wait_pod_phase(
            name, "Running", namespace=namespace, timeout=timeout)

    def delete_pod(self, name, namespace="default"):
        self.core_v1_api.delete_namespaced_pod(name=name, namespace=namespace)

    def create_configmap(self, name, data, namespace="default"):
        config_map = client.V1ConfigMap()
        config_map.metadata = client.V1ObjectMeta(name=name)
        config_map.data = data
        return self.core_v1_api.create_namespaced_config_map(
            body=config_map, namespace=namespace)

    def create_configmap_from_file(self, name, file_path, namespace="default",
                                   config_map_file_name=""):
        with open(file_path, "r") as f:
            file_content = f.read()
        if config_map_file_name == "":
            config_map_file_name = os.path.basename(file_path)
        data = {
            config_map_file_name: file_content
        }
        return self.create_configmap(name, data, namespace=namespace)

    def create_secret(self, name, secret_name, secret_value,
                      namespace="default", secret_type="Opaque"):
        secret_data = {
            secret_name: base64.b64encode(secret_value.encode()).decode()
        }
        return self._create_secret(name, secret_data, namespace, secret_type)

    def create_secret_from_file(self, name, file_path, namespace="default",
                                secret_file_name=""):
        with open(file_path, "r") as f:
            file_content = f.read()
        if secret_file_name == "":
            secret_file_name = os.path.basename(file_path)
        data = {
            secret_file_name: base64.b64encode(file_content.encode()).decode(),
        }
        return self._create_secret(name, data, namespace=namespace)

    def create_from_yaml(self, file_path, namespace="default", verbose=True):
        return utils.create_from_yaml(
            self.api_client, file_path, namespace=namespace, verbose=verbose)

    def _create_secret(self, name, data, namespace="default",
                       secret_type="Opaque"):
        secret = client.V1Secret()
        secret.metadata = client.V1ObjectMeta(name=name)
        secret.type = secret_type
        secret.data = data
        return self.core_v1_api.create_namespaced_secret(
            namespace=namespace, body=secret)

    def _parse_log_line(self, line):
        split_at = line.find(' ')
        if split_at == -1:
            return None, line
        timestamp = line[:split_at]
        message = line[split_at + 1:].rstrip()
        return timestamp, message
