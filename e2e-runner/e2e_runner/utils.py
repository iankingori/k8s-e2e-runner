import configargparse
import os
import subprocess
import tempfile
import time
import socket
from threading import Timer

import jinja2
import six
import tenacity

from e2e_runner import (
    exceptions,
    logger,
)

logging = logger.get_logger(__name__)


def run_cmd(cmd, timeout=(3 * 3600), env=None, stdout=False, stderr=False,
            cwd=None, shell=False, sensitive=False):

    def kill_proc_timout(proc):
        proc.kill()
        raise exceptions.CmdTimeoutExceeded(
            "Timeout of {} exceeded for cmd {}".format(timeout, cmd))

    FNULL = open(os.devnull, "w")
    f_stderr = FNULL
    f_stdout = FNULL
    if stdout is True:
        f_stdout = subprocess.PIPE
    if stderr is True:
        f_stderr = subprocess.PIPE
    if not sensitive:
        logging.info("Calling %s", " ".join(cmd))
    if shell:
        cmd = " ".join(cmd)
    proc = subprocess.Popen(
        cmd, env=env, stdout=f_stdout, stderr=f_stderr, cwd=cwd, shell=shell)
    timer = Timer(timeout, kill_proc_timout, [proc])
    try:
        timer.start()
        stdout, stderr = proc.communicate()
        return stdout, stderr, proc.returncode
    finally:
        timer.cancel()


def get_go_path():
    return os.environ.get("GOPATH") or "/go"


def get_k8s_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "k8s.io", "kubernetes")


def retry_on_error(max_attempts=5, max_sleep_seconds=60):
    return tenacity.retry(
        stop=tenacity.stop_after_attempt(max_attempts),
        wait=tenacity.wait_exponential(max=max_sleep_seconds),
        reraise=True)


@retry_on_error()
def download_file(url, dst):
    _, _, ret = run_cmd(["wget", "-q", url, "-O", dst], stderr=True)
    if ret != 0:
        logging.error("Failed to download file: %s", url)
    return ret


def get_kubectl_bin():
    if os.environ.get("KUBECTL_PATH"):
        return os.environ.get("KUBECTL_PATH")
    else:
        return os.path.join(get_k8s_folder(), "cluster/kubectl.sh")


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
    except (six.moves.builtins.ConnectionRefusedError,
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
        err_msg = "Connection failed on port {}".format(port)
        logging.error(err_msg)
        raise exceptions.ConnectionFailed(err_msg)


def run_shell_cmd(cmd, cwd=None, env=None, sensitive=False,
                  timeout=(3 * 3600)):
    out, err, ret = run_cmd(
        cmd, timeout=timeout, stdout=True, stderr=True, shell=True,
        cwd=cwd, env=env, sensitive=sensitive)
    if ret != 0:
        raise exceptions.ShellCmdFailed(
            "Failed to execute: {}. Error: {}".format(' '.join(cmd), err))
    return (out, err)


def run_async_shell_cmd(cmd, args, log_prefix=""):
    def process_stdout(line):
        logging.info(log_prefix + line.strip())

    def process_stderr(line):
        logging.warning(log_prefix + line.strip())

    proc = cmd(args, _out=process_stdout, _err=process_stderr, _bg=True)
    return proc


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
    _, err, ret = run_cmd(cmd, timeout=900, stderr=True)
    if ret != 0:
        raise exceptions.GitCloneFailed(
            "Git Clone Failed with error: {}.".format(err))
    logging.info("Succesfully cloned git repo.")


def str2bool(v):
    if v.lower() == 'true':
        return True
    elif v.lower() == 'false':
        return False
    else:
        raise configargparse.ArgumentTypeError(
            'Boolean value expected')


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
        "{}@{}".format(ssh_user, ssh_address),
        "bash", "-s"]
    with tempfile.NamedTemporaryFile() as f:
        f.write(script.encode())
        f.flush()
        if return_result:
            ssh_cmd += ["<", f.name]
            return run_shell_cmd(ssh_cmd, timeout=timeout)
        with open(f.name, "rb", 0) as g:
            subprocess.check_call(ssh_cmd, stdin=g)


def rsync_upload(local_path, remote_path,
                 ssh_user, ssh_address, ssh_key_path=None):
    ssh_cmd = ("ssh -q "
               "-o StrictHostKeyChecking=no "
               "-o UserKnownHostsFile=/dev/null")
    if ssh_key_path:
        ssh_cmd += " -i {}".format(ssh_key_path)
    run_shell_cmd([
        "rsync", "-r", "-e", '"{}"'.format(ssh_cmd),
        local_path,
        "{}@{}:{}".format(ssh_user, ssh_address, remote_path)])
