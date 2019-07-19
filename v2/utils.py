import subprocess
import os
import log
from threading import Timer
import errno
import shutil
import glob
import constants

logging = log.getLogger(__name__)

class CmdTimeoutExceededException(Exception):
    pass

def run_cmd(cmd, timeout=50000, env=None, stdout=False,
            stderr=False, cwd=None, shell=False, sensitive=False):

    def kill_proc_timout(proc):
        proc.kill()
        raise CmdTimeoutExceededException("Timeout of %s exceeded for cmd %s" % (timeout, cmd))

    FNULL = open(os.devnull, "w")
    f_stderr = FNULL
    f_stdout = FNULL
    if stdout == True:
        f_stdout = subprocess.PIPE
    if stderr == True:
        f_stderr = subprocess.PIPE
    if not sensitive:
        logging.info("Calling %s" % " ".join(cmd))
    if shell:
        cmd = " ".join(cmd)
    proc = subprocess.Popen(cmd, env=env, stdout=f_stdout, stderr=f_stderr, cwd=cwd, shell=shell)
    timer=Timer(timeout, kill_proc_timout, [proc])
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
    logging.info("Cloning git repo %s on branch %s in location %s" % (repo, branch, dest_path if not None else os.getcwd()))
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

def get_sdn_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "github.com", "Microsoft", "windows-container-networking")

def build_containerd_binaries(containerd_path=None):
    containerd_path = containerd_path if containerd_path else get_containerd_folder()
    logging.info("Building containerd binaries")
    cmd = ["GOOS=windows", "make"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=containerd_path, shell=True)

    if ret != 0:
        logging.error("Failed to build containerd windows binaries with error: %s" % err)
        raise Exception("Failed to build containerd windows binaries with error: %s" % err)
    
    logging.info("Succesfully built containerd binaries.")
    logging.info("Copying built bins to central location")
    containerd_bins_location = os.path.join(containerd_path, constants.CONTAINERD_BINS_LOCATION)
    for path in glob.glob("%s/*" % containerd_bins_location):
        shutil.copy(path, get_bins_path())


def build_sdn_binaries(sdn_path=None):
    sdn_path = sdn_path if sdn_path else get_sdn_folder()
    logging.info("Build sdn binaries")
    cmd = ["GOOS=windows", "make", "all"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=sdn_path, shell=True)

    if ret != 0:
        logging.error("Failed to build sdn windows binaries with error: %s" % err)
        raise Exception("Failed to build sdn windows binaries with error: %s" % err)
    
    logging.info("Successfuly build sdn binaries.")
    logging.info("Copying built bins to central location")
    sdn_bins_location = os.path.join(sdn_path, constants.SDN_BINS_LOCATION)
    for path in glob.glob("%s/*" % sdn_bins_location):
        shutil.copy(path, get_bins_path())

def build_k8s_binaries(k8s_path=None):
    k8s_path = k8s_path if k8s_path else get_k8s_folder()
    logging.info("Building K8s Binaries:")
    logging.info("Build k8s linux binaries.")
    cmd = ["make", 'WHAT="cmd/kube-apiserver cmd/kube-controller-manager cmd/kubelet cmd/kubectl cmd/kube-scheduler cmd/kube-proxy"']
    
    _, err, ret = run_cmd(cmd, stderr=True, cwd=k8s_path, shell=True)

    if ret != 0:
        logging.error("Failed to build k8s linux binaries with error: %s" % err)
        raise Exception("Failed to build k8s linux binaries with error: %s" % err)
    
    cmd = ["make", 'WHAT="cmd/kubelet cmd/kubectl cmd/kube-proxy"', "KUBE_BUILD_PLATFORMS=windows/amd64"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=k8s_path, shell=True)
    if ret != 0:
        logging.error("Failed to build k8s windows binaries with error: %s" % err)
        raise Exception("Failed to build k8s windows binaries with error: %s" % err)
    
    logging.info("Succesfully built k8s binaries.")
    logging.info("Copying built bins to central location.")
    k8s_linux_bins_location = os.path.join(k8s_path, constants.KUBERNETES_LINUX_BINS_LOCATION)
    for path in glob.glob("%s/*" % k8s_linux_bins_location):
        shutil.copy(path, get_bins_path())
    k8s_windows_bins_location = os.path.join(k8s_path, constants.KUBERNETES_WINDOWS_BINS_LOCATION)
    for path in glob.glob("%s/*" % k8s_windows_bins_location):
        shutil.copy(path, get_bins_path())


def get_k8s(repo, branch):
    logging.info("Get Kubernetes.")
    k8s_path = get_k8s_folder()
    clone_repo(repo, branch, k8s_path)

def download_file(url, dst):
    cmd = ["wget", url, "-O", dst]
    _, err, ret = run_cmd(cmd)

    if ret != 0:
        logging.error("Failed to download file: %s" % url)

def run_ssh_cmd(cmd, user, host,):
    cmd = ["ssh","-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"]
