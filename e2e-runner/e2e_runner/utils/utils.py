import os
import socket
import subprocess
import tarfile
import tempfile
import time
from collections import OrderedDict
from urllib.request import urlretrieve

import configargparse
import jinja2
import sh
import tenacity
from e2e_runner import exceptions as e2e_exceptions
from e2e_runner import logger as e2e_logger

logging = e2e_logger.get_logger(__name__)

LAST_LOG_TIMESTAMP = None


def str2bool(v):
    if v.lower() == 'true':
        return True
    elif v.lower() == 'false':
        return False
    else:
        raise configargparse.ArgumentTypeError("Boolean value expected")


def retry_on_error(max_attempts=5, max_sleep_seconds=60):
    return tenacity.retry(
        stop=tenacity.stop_after_attempt(max_attempts),  # pyright: ignore
        wait=tenacity.wait_exponential(max=max_sleep_seconds),  # pyright: ignore # noqa:
        reraise=True)


def render_template(template_file, output_file, context={}, searchpath="/"):
    template_loader = jinja2.FileSystemLoader(searchpath=searchpath)
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template(template_file)
    with open(output_file, 'w') as f:
        f.write(template.render(context))


def check_port_open(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        s.connect((host, port))
        return True
    except (ConnectionRefusedError,
            socket.timeout,
            OSError):
        return False
    finally:
        s.close()


def wait_for_port_connectivity(address, port, max_wait=300):
    i = 0
    while not check_port_open(address, port) and i < max_wait:
        time.sleep(1)
        i += 1
    if i == max_wait:
        err_msg = f"Connection failed on port {port}"
        logging.error(err_msg)
        raise e2e_exceptions.ConnectionFailed(err_msg)


def run_shell_cmd(cmd, cwd=None, env=None, timeout=(3 * 3600),
                  capture_output=False, hide_cmd=False):
    cmd_string = " ".join(cmd)
    if not hide_cmd:
        logging.info(cmd_string)
    p = subprocess.run(
        args=cmd_string, cwd=cwd, env=env, timeout=timeout,
        capture_output=capture_output, shell=True, check=True)
    return (p.stdout, p.stderr)


def clone_git_repo(repo_url, branch_name, local_dir):
    if os.path.exists(local_dir) and len(os.listdir(local_dir)) > 0:
        run_shell_cmd(cmd=["git", "fetch"], cwd=local_dir)
        run_shell_cmd(cmd=["git", "checkout", branch_name], cwd=local_dir)
        return
    cmd = ["git", "clone", "--single-branch",
           "--branch", branch_name, repo_url]
    if local_dir:
        cmd.append(local_dir)
    logging.info("Cloning git repo %s on branch %s", repo_url, branch_name)
    run_shell_cmd(cmd, timeout=900)
    logging.info("Succesfully cloned git repo.")


def run_remote_ssh_cmd(cmd, ssh_user, ssh_address, ssh_key_path=None,
                       cwd="~", timeout=3600, return_result=False):
    script = """
    set -o nounset
    set -o pipefail
    set -o errexit
    cd {0}
    {1}
    """.format(cwd, "\n".join(cmd))
    ssh_cmd = ["ssh", "-q"]
    if ssh_key_path:
        ssh_cmd += ["-i", ssh_key_path]
    ssh_cmd += [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        f"{ssh_user}@{ssh_address}",
        "bash", "-s"]
    with tempfile.NamedTemporaryFile() as f:
        f.write(script.encode())
        f.flush()
        if return_result:
            ssh_cmd += ["<", f.name]
            return run_shell_cmd(
                cmd=ssh_cmd,
                timeout=timeout,
                capture_output=True,
                hide_cmd=True,
            )
        with open(f.name, "rb", 0) as g:
            subprocess.check_call(ssh_cmd, stdin=g)


def rsync_upload(local_path, remote_path,
                 ssh_user, ssh_address, ssh_key_path=None, delete=True):
    ssh_cmd = ("ssh -q "
               "-o StrictHostKeyChecking=no "
               "-o UserKnownHostsFile=/dev/null")
    if ssh_key_path:
        ssh_cmd += f" -i {ssh_key_path}"
    rsync_cmd = ["rsync", "-rlptD", f"-e='{ssh_cmd}'"]
    if delete:
        rsync_cmd.append("--delete")
    rsync_cmd.extend([local_path, f"{ssh_user}@{ssh_address}:{remote_path}"])
    run_shell_cmd(rsync_cmd)


def rsync_download(remote_path, local_path,
                   ssh_user, ssh_address, ssh_key_path=None, delete=True):
    ssh_cmd = ("ssh -q "
               "-o StrictHostKeyChecking=no "
               "-o UserKnownHostsFile=/dev/null")
    if ssh_key_path:
        ssh_cmd += f" -i {ssh_key_path}"
    rsync_cmd = ["rsync", "-rlptD", f"-e='{ssh_cmd}'"]
    if delete:
        rsync_cmd.append("--delete")
    rsync_cmd.extend([f"{ssh_user}@{ssh_address}:{remote_path}", local_path])
    run_shell_cmd(rsync_cmd)


def make_tgz_archive(source_dir, output_file):
    with tarfile.open(output_file, "w:gz") as tar:
        tar.add(source_dir, arcname=os.path.basename(source_dir))


@retry_on_error()
def download_file(url, dest):
    urlretrieve(url, dest)


def sort_dict_by_value(d):
    return OrderedDict(sorted(d.items(), key=lambda item: item[1]))


def get_kubectl_bin():
    if os.environ.get("KUBECTL_PATH"):
        return os.environ.get("KUBECTL_PATH")
    # assume kubectl is in the PATH
    return "kubectl"


def exec_kubectl(args, env=None, timeout=(3 * 3600),
                 capture_output=False, hide_cmd=False,
                 retries=5, retries_max_sleep_seconds=30,
                 allowed_error_codes=[]):
    kubectl_cmd = [get_kubectl_bin(), *args]
    for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_attempt(retries),  # pyright: ignore
            wait=tenacity.wait_exponential(max=retries_max_sleep_seconds),  # pyright: ignore # noqa:
            reraise=True):
        with attempt:
            stdout = None
            stderr = None
            try:
                stdout, stderr = run_shell_cmd(
                    cmd=kubectl_cmd,
                    env=env,
                    timeout=timeout,
                    capture_output=capture_output,
                    hide_cmd=hide_cmd)
            except subprocess.CalledProcessError as ex:
                if ex.returncode not in allowed_error_codes:
                    raise ex
            if stdout:
                stdout = stdout.decode().strip()
            if stderr:
                stderr = stderr.decode().strip()
            return stdout, stderr


def kubectl_watch_logs(k8s_client, pod_name, namespace="default",
                       container_name=None):

    def print_stdout(line):
        global LAST_LOG_TIMESTAMP
        split_at = line.find(' ')
        LAST_LOG_TIMESTAMP = line[:split_at]
        line = line[split_at + 1:]
        print(line, end="")

    def print_stderr(line):
        print(line, end="")

    if not container_name:
        pod = k8s_client.get_pod(pod_name, namespace)
        container_name = pod.spec.containers[0].name

    kubectl_args = ["logs", "--namespace", namespace, pod_name,
                    "--container", container_name,
                    "--follow", "--timestamps"]
    global LAST_LOG_TIMESTAMP
    while True:
        args = kubectl_args
        if LAST_LOG_TIMESTAMP:
            args += ["--since-time", LAST_LOG_TIMESTAMP]
        p = sh.kubectl(*args, _out=print_stdout, _err=print_stderr,
                       _bg=True, _bg_exc=False)
        try:
            p.wait()
        except Exception:
            logging.warning(
                "Pod (%s) container (%s) log read interrupted. Resuming log "
                "read if pod container is still running...", pod_name,
                container_name)

        container_status = k8s_client.get_pod_container_status(
            pod_name, container_name, namespace)
        if container_status.state.terminated:
            LAST_LOG_TIMESTAMP = None
            break

    logging.info("Pod (%s) container (%s) log read finished. "
                 "Waiting until pod is not running anymore...",
                 pod_name, container_name)
    while k8s_client.is_pod_running(pod_name, namespace):
        time.sleep(1)


def get_k8s_agents_private_addresses(operating_system):
    private_addresses, _ = exec_kubectl(
        args=[
            "get", "nodes",  # pyright: ignore
            "-o", "jsonpath=\"{{.items[?(@.status.nodeInfo.operatingSystem == '{}')].status.addresses[?(@.type == 'InternalIP')].address}}\"".format(operating_system),  # pyright: ignore # noqa:
        ],
        capture_output=True,
        hide_cmd=True,
    )
    return private_addresses.strip().split()  # pyright: ignore


def exec_pod(pod_name, cmd):
    exec_kubectl(["exec", pod_name, "--", *cmd])


def upload_to_pod(pod_name, local_path, remote_path):
    exec_kubectl(["cp", local_path, f"{pod_name}:{remote_path}"])


def download_from_pod(pod_name, remote_path, local_path):
    exec_kubectl(["cp", f"{pod_name}:{remote_path}", local_path])


def validate_non_empty_env_variables(env_vars_names=[]):
    for var_name in env_vars_names:
        if not os.environ.get(var_name):
            raise e2e_exceptions.EnvVarNotFound(
                f"Env variable {var_name} is not set")


def get_file_content(file_path):
    with open(file_path) as f:
        return f.read().strip()
