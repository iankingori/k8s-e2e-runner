import configargparse
import os
import functools
import subprocess
import time
import traceback
import socket
from threading import Timer

import jinja2
import six

from e2e_runner import logger

logging = logger.get_logger(__name__)


class CmdTimeoutExceededException(Exception):
    pass


def run_cmd(cmd,
            timeout=50000,
            env=None,
            stdout=False,
            stderr=False,
            cwd=None,
            shell=False,
            sensitive=False):
    def kill_proc_timout(proc):
        proc.kill()
        raise CmdTimeoutExceededException("Timeout of %s exceeded for cmd %s" %
                                          (timeout, cmd))

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
    proc = subprocess.Popen(cmd,
                            env=env,
                            stdout=f_stdout,
                            stderr=f_stderr,
                            cwd=cwd,
                            shell=shell)
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


def download_file(url, dst):
    cmd = ["wget", "-q", url, "-O", dst]
    _, _, ret = run_cmd(cmd, stderr=True)

    if ret != 0:
        logging.error("Failed to download file: %s", url)

    return ret


def get_kubectl_bin():
    if os.environ.get("KUBECTL_PATH"):
        return os.environ.get("KUBECTL_PATH")
    else:
        return os.path.join(get_k8s_folder(), "cluster/kubectl.sh")


def get_exception_details():
    return traceback.format_exc()


def retry_on_error(max_attempts=5, sleep_seconds=0, terminal_exceptions=[]):
    def _retry_on_error(func):
        @functools.wraps(func)
        def _exec_retry(*args, **kwargs):
            i = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except KeyboardInterrupt:
                    logging.debug("Got a KeyboardInterrupt, skip retrying")
                    raise
                except Exception as ex:
                    found_terminal_exceptions = [
                        isinstance(ex, tex) for tex in terminal_exceptions
                    ]
                    if any(found_terminal_exceptions):
                        raise
                    i += 1
                    if i < max_attempts:
                        logging.warning(
                            "Exception occurred, retrying (%d/%d):\n%s", i,
                            max_attempts, get_exception_details())
                        time.sleep(sleep_seconds)
                    else:
                        raise

        return _exec_retry

    return _retry_on_error


def render_template(template_file, output_file, context={}, searchpath="/"):
    template_loader = jinja2.FileSystemLoader(searchpath=searchpath)
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template(template_file)

    with open(output_file, 'w') as f:
        f.write(template.render(context))


def _check_port_open(host, port):
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
    while not _check_port_open(address, port) and i < max_wait:
        time.sleep(1)
        i += 1
    if i == max_wait:
        err_msg = "Connection failed on port %s" % port
        logging.error(err_msg)
        raise Exception(err_msg)


def run_shell_cmd(cmd, cwd=None, env=None, sensitive=False,
                  timeout=(3 * 3600)):

    out, err, ret = run_cmd(
        cmd, timeout=timeout, stdout=True, stderr=True, shell=True,
        cwd=cwd, env=env, sensitive=sensitive)

    if ret != 0:
        raise Exception("Failed to execute: %s. Error: %s" %
                        (' '.join(cmd), err))

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
        raise Exception("Git Clone Failed with error: %s." % err)
    logging.info("Succesfully cloned git repo.")


def str2bool(v):
    if v.lower() == 'true':
        return True
    elif v.lower() == 'false':
        return False
    else:
        raise configargparse.ArgumentTypeError(
            'Boolean value expected')
