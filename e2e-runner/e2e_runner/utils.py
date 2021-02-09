import configargparse
import os
import functools
import subprocess
import errno
import random
import re
import shutil
import string
import tempfile
import time
import glob
import traceback
import socket
from base64 import b64encode
from threading import Timer

import jinja2
import six
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5 as Cipher_PKCS1_v1_5

from e2e_runner import logger, constants

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


def clone_repo(repo, branch="master", dest_path=None):
    cmd = ["git", "clone", "--single-branch", "--branch", branch, repo]
    if dest_path:
        cmd.append(dest_path)
    logging.info("Cloning git repo %s on branch %s", repo, branch)
    _, err, ret = run_cmd(cmd, timeout=900, stderr=True)
    if ret != 0:
        raise Exception("Git Clone Failed with error: %s." % err)
    logging.info("Succesfully cloned git repo.")


def rm_dir(dir_path):
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path, ignore_errors=True)


def mkdir_p(dir_path):
    try:
        os.mkdir(dir_path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def generate_random_password(key, length=20):
    passw = ''.join(
        random.choice(string.ascii_lowercase) for i in range(length // 4))
    passw += ''.join(
        random.choice(string.ascii_uppercase) for i in range(length // 4))
    passw += ''.join(random.choice(string.digits) for i in range(length // 4))
    passw += ''.join(
        random.choice("!?.,@#$%^&=")
        for i in range(length - 3 * (length // 4)))
    passw = ''.join(random.sample(passw, len(passw)))

    pubKeyObj = RSA.importKey(key)
    cipher = Cipher_PKCS1_v1_5.new(pubKeyObj)
    cipher_text = cipher.encrypt(passw.encode())
    enc_pwd = b64encode(cipher_text)
    logging.info("Encrypted pass: %s", enc_pwd)

    return passw


def get_go_path():
    return os.environ.get("GOPATH") if os.environ.get("GOPATH") else "/go"


def get_bins_path():
    # returns location where all built bins should be stored
    path = os.path.join("/tmp/bins")
    mkdir_p(path)
    return path


def get_k8s_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "k8s.io", "kubernetes")


def get_containerd_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "github.com", "containerd", "cri")


def get_containerd_shim_folder(fromVendor=False):
    gopath = get_go_path()

    if fromVendor:
        containerd_path = get_containerd_folder()
        path_prefix = os.path.join(containerd_path, "vendor")
    else:
        path_prefix = os.path.join(gopath, "src")

    return os.path.join(path_prefix, "github.com", "Microsoft", "hcsshim")


def get_ctr_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "github.com", "containerd",
                        "containerd")


def get_sdn_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "github.com", "Microsoft",
                        "windows-container-networking")


def build_containerd_binaries(containerd_path=None, ctr_path=None):
    if not containerd_path:
        containerd_path = get_containerd_folder()
    if not ctr_path:
        ctr_path = get_ctr_folder()

    logging.info("Building containerd binaries")
    cmd = ["GOOS=windows", "make"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=containerd_path, shell=True)

    if ret != 0:
        logging.error(
            "Failed to build containerd windows binaries with error: %s", err)
        raise Exception(
            "Failed to build containerd windows binaries with error: %s" % err)

    logging.info("Succesfully built containerd binaries.")

    logging.info("Building ctr")
    cmd = ["GOOS=windows", "make bin/ctr.exe"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=ctr_path, shell=True)

    if ret != 0:
        logging.error(
            "Failed to build ctr windows binary with error: %s", err)
        raise Exception(
            "Failed to build ctr windows binary with error: %s" % err)

    logging.info("Succesfully built ctr binary.")
    logging.info("Copying built bins to central location")

    containerd_bins_location = os.path.join(containerd_path,
                                            constants.CONTAINERD_BINS_LOCATION)
    for path in glob.glob("%s/*" % containerd_bins_location):
        shutil.copy(path, get_bins_path())

    shutil.copy(os.path.join(ctr_path, constants.CONTAINERD_CTR_LOCATION),
                get_bins_path())


def build_containerd_shim(containerd_shim_path=None, fromVendor=False):
    if not containerd_shim_path:
        get_containerd_shim_folder()

    logging.info("Building containerd shim")

    if fromVendor:
        vendoring_path = get_containerd_folder()
        cmd = ["go", "get", "github.com/LK4D4/vndr"]
        _, err, ret = run_cmd(cmd, stderr=True, shell=True)
        if ret != 0:
            logging.error("Failed to install vndr with error: %s", err)
            raise Exception("Failed to install vndr with error: %s" % err)

        cmd = ["vndr", "-whitelist", "hcsshim", "github.com/Microsoft/hcsshim"]
        _, err, ret = run_cmd(cmd, stderr=True, cwd=vendoring_path, shell=True)
        if ret != 0:
            logging.error("Failed to install vndr with error: %s", err)
            raise Exception("Failed to install vndr with error: %s" % err)

    cmd = [
        "GOOS=windows", "go", "build", "-o", constants.CONTAINERD_SHIM_BIN,
        constants.CONTAINERD_SHIM_DIR
    ]

    _, err, ret = run_cmd(cmd,
                          stderr=True,
                          cwd=containerd_shim_path,
                          shell=True)

    if ret != 0:
        logging.error("Failed to build containerd shim with error: %s", err)
        raise Exception("Failed to build containerd shim with error: %s" % err)

    logging.info("Succesfully built containerd shim.")
    logging.info("Copying built shim to central location")
    containerd_shim_bin = os.path.join(containerd_shim_path,
                                       constants.CONTAINERD_SHIM_BIN)
    shutil.copy(containerd_shim_bin, get_bins_path())


def build_sdn_binaries(sdn_path=None):
    if not sdn_path:
        sdn_path = get_sdn_folder()

    logging.info("Build sdn binaries")
    cmd = ["GOOS=windows", "make", "all"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=sdn_path, shell=True)

    if ret != 0:
        logging.error(
            "Failed to build sdn windows binaries with error: %s", err)
        raise Exception(
            "Failed to build sdn windows binaries with error: %s" % err)

    logging.info("Successfuly built sdn binaries.")
    logging.info("Copying built bins to central location")
    sdn_bins_location = os.path.join(sdn_path, constants.SDN_BINS_LOCATION)
    for path in glob.glob("%s/*" % sdn_bins_location):
        shutil.copy(path, get_bins_path())


def build_k8s_binaries(k8s_path=None):
    if not k8s_path:
        k8s_path = get_k8s_folder()

    logging.info("Building K8s Binaries:")
    logging.info("Build K8s linux binaries.")

    components = ('cmd/kube-controller-manager '
                  'cmd/kube-apiserver '
                  'cmd/kube-scheduler '
                  'cmd/kube-proxy '
                  'cmd/kubelet '
                  'cmd/kubectl')
    cmd = ["make", 'WHAT="%s"' % components]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=k8s_path, shell=True)

    if ret != 0:
        logging.error(
            "Failed to build k8s linux binaries with error: %s", err)
        raise Exception(
            "Failed to build k8s linux binaries with error: %s" % err)

    cmd = [
        "make", 'WHAT="cmd/kubelet cmd/kubectl cmd/kube-proxy"',
        "KUBE_BUILD_PLATFORMS=windows/amd64"
    ]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=k8s_path, shell=True)
    if ret != 0:
        logging.error(
            "Failed to build k8s windows binaries with error: %s", err)
        raise Exception(
            "Failed to build k8s windows binaries with error: %s" % err)

    logging.info("Succesfully built k8s binaries.")

    logging.info("Copying built bins to central location.")

    k8s_linux_bins_location = os.path.join(
        k8s_path, constants.KUBERNETES_LINUX_BINS_LOCATION)
    for path in glob.glob("%s/*" % k8s_linux_bins_location):
        shutil.copy(path, get_bins_path())

    k8s_windows_bins_location = os.path.join(
        k8s_path, constants.KUBERNETES_WINDOWS_BINS_LOCATION)
    for path in glob.glob("%s/*" % k8s_windows_bins_location):
        shutil.copy(path, get_bins_path())


def get_k8s(repo, branch):
    logging.info("Get Kubernetes.")
    k8s_path = get_k8s_folder()
    clone_repo(repo, branch, k8s_path)


def download_file(url, dst):
    cmd = ["wget", "-q", url, "-O", dst]
    _, _, ret = run_cmd(cmd, stderr=True)

    if ret != 0:
        logging.error("Failed to download file: %s", url)

    return ret


def run_ssh_cmd(cmd, user, host):
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o",
        "UserKnownHostsFile=/dev/null",
        "%s@%s" % (user, host),
        "'%s'" % cmd
    ]
    run_cmd(ssh_cmd, stdout=True, stderr=True)


def sed_inplace(filename, pattern, repl):
    pattern_compiled = re.compile(pattern)

    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_file:
        with open(filename) as src_file:
            for line in src_file:
                tmp_file.write(pattern_compiled.sub(repl, line))

    shutil.copystat(filename, tmp_file.name)
    shutil.move(tmp_file.name, filename)


def get_kubectl_bin():
    if os.environ.get("KUBECTL_PATH"):
        return os.environ.get("KUBECTL_PATH")
    else:
        return os.path.join(get_k8s_folder(), "cluster/kubectl.sh")


def wait_for_ready_pod(pod_name, timeout=300):
    logging.info("Waiting up to %d seconds for pod %s to be ready.", timeout,
                 pod_name)

    kubectl = get_kubectl_bin()
    start = time.time()
    cmd = [
        kubectl, "get", "pods",
        "--output=custom-columns=READY:.status.containerStatuses[].ready",
        "--no-headers", pod_name
    ]

    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            return False

        out, err, ret = run_cmd(cmd,
                                stdout=True,
                                stderr=True,
                                shell=True,
                                sensitive=True)

        if ret != 0:
            logging.error("Failed to get pod ready status: %s", err)
            raise Exception("Failed to get pod ready status: %s" % err)

        pod_ready = out.strip()
        if pod_ready == "true":
            return True

        time.sleep(5)


def daemonset_cleanup(daemonset_yaml, daemonset_name, timeout=600):
    logging.info("Cleaning up daemonset: %s", daemonset_name)

    kubectl = get_kubectl_bin()
    start = time.time()
    cmd = [kubectl, "delete", "-f", daemonset_yaml]
    out, err, ret = run_cmd(cmd, stdout=True, stderr=True, shell=True)

    if ret != 0:
        logging.error("Failed to delete daemonset: %s", err)
        raise Exception("Failed to delete daemonset: %s" % err)

    cmd = [
        kubectl, "get", "pods",
        "--selector=name=%s" % daemonset_name, "--no-headers",
        "--ignore-not-found"
    ]

    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            return False

        out, err, ret = run_cmd(cmd,
                                stdout=True,
                                stderr=True,
                                shell=True,
                                sensitive=True)

        if ret != 0:
            logging.error("Failed to get daemonset: %s", err)
            raise Exception("Failed to get daemonset: %s" % err)

        if out.strip() == "":
            return True

        time.sleep(5)


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

    clone_repo(repo_url, branch_name, local_dir)


def str2bool(v):
    if v.lower() == 'true':
        return True
    elif v.lower() == 'false':
        return False
    else:
        raise configargparse.ArgumentTypeError(
            'Boolean value expected')
