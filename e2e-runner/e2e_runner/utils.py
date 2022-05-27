import configargparse
import os
import subprocess
import tempfile
import time
import socket
import tarfile
from urllib.request import urlretrieve

import jinja2
import tenacity

from e2e_runner import exceptions as e2e_exceptions
from e2e_runner import logger as e2e_logger

logging = e2e_logger.get_logger(__name__)


def str2bool(v):
    if v.lower() == 'true':
        return True
    elif v.lower() == 'false':
        return False
    else:
        raise configargparse.ArgumentTypeError("Boolean value expected")


def retry_on_error(max_attempts=5, max_sleep_seconds=60):
    return tenacity.retry(
        stop=tenacity.stop_after_attempt(max_attempts),
        wait=tenacity.wait_exponential(max=max_sleep_seconds),
        reraise=True)


def get_kubectl_bin():
    if os.environ.get("KUBECTL_PATH"):
        return os.environ.get("KUBECTL_PATH")
    # assume kubectl is in the PATH
    return "kubectl"


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
            return run_shell_cmd(ssh_cmd, timeout=timeout, capture_output=True)
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


def label_linux_nodes_no_schedule():
    kubectl = get_kubectl_bin()
    out, _ = run_shell_cmd(
        cmd=[
            kubectl, "get", "nodes", "--selector",
            "kubernetes.io/os=linux", "--no-headers", "-o",
            "custom-columns=NAME:.metadata.name"
        ],
        capture_output=True)
    linux_nodes = out.decode().strip().split("\n")
    for node in linux_nodes:
        run_shell_cmd([
            kubectl, "taint", "nodes", "--overwrite", node,
            "node-role.kubernetes.io/master=:NoSchedule"
        ])
        run_shell_cmd([
            kubectl, "label", "nodes", "--overwrite", node,
            "node-role.kubernetes.io/master=NoSchedule"
        ])
