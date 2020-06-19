#!/usr/bin/env python3

import errno
import logging
import json
import tempfile
import os
import socket
import time

import configargparse
import sh

p = configargparse.get_argument_parser()
logger = logging.getLogger("bootstrap")

JOB_REPO_CLONE_DST = os.path.join(tempfile.gettempdir(), "k8s-e2e-runner")
DEFAULT_JOB_CONFIG_PATH = os.path.join(tempfile.gettempdir(), "job_config.txt")


def call(cmd, args):
    def process_stdout(line):
        logger.info(line.strip())

    def process_stderr(line):
        logger.warning(line.strip())

    proc = cmd(args,
               _out=process_stdout,
               _err=process_stderr,
               _bg=True,
               _bg_exc=False)
    proc.wait()


def parse_args():
    p.add("--job-config", help="Configuration for job to be ran. URL or file.")
    p.add(
        "--job-repo",
        default="http://github.com/e2e-win/k8s-e2e-runner",
        help="Respository for job runner.",
    )
    p.add("--job-branch", default="master", help="Branch for job runner.")
    p.add("--service-account", help="Service account for gcloud login.")
    p.add("--log-path", default="/tmp/civ2_logs", help="Local logs path")
    p.add("--gs", help="Log Google bucket")
    p.add("job_args", nargs=configargparse.REMAINDER)

    opts = p.parse_known_args()

    return opts


def gcloud_login(service_account):
    logger.info("Logging in to gcloud.")
    cmd_args = [
        "auth", "activate-service-account", "--no-user-output-enabled",
        "--key-file=%s" % service_account
    ]
    call(sh.gcloud, cmd_args)


def get_job_config_file(job_config):
    if job_config is None:
        return None
    if os.path.isfile(job_config):
        return os.path.abspath(job_config)
    download_file(job_config, DEFAULT_JOB_CONFIG_PATH)
    return DEFAULT_JOB_CONFIG_PATH


def get_cluster_name():
    # The cluster name is composed of the first 8 chars of the prowjob in case
    # it exists
    return os.getenv("PROW_JOB_ID", "0000-0000-0000-0000")[:7]


def setup_logging(log_out_file):
    level = logging.DEBUG
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s : %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )
    stream = logging.StreamHandler()
    stream.setLevel(level)
    stream.setFormatter(formatter)

    file_log = logging.FileHandler(log_out_file)
    file_log.setLevel(level)
    file_log.setFormatter(formatter)

    logger.addHandler(stream)
    logger.addHandler(file_log)


def clone_repo(repo, branch="master", dest_path=None):
    cmd_args = ["clone", "-q", "--single-branch", "--branch", branch, repo]
    if dest_path:
        cmd_args.append(dest_path)
    logger.info("Cloning git repo %s on branch %s in location %s", repo,
                branch, dest_path if not None else os.getcwd())
    call(sh.git, cmd_args)
    logger.info("Succesfully cloned git repo.")


def mkdir_p(dir_path):
    try:
        os.mkdir(dir_path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def download_file(url, dst):
    call(sh.wget, ["-q", url, "-O", dst])


def create_log_paths(log_path, remote_base):
    # TODO: Since we upload to gcloud we should make sure the user specifies
    # an empty path

    mkdir_p(log_path)
    artifacts_path = os.path.join(log_path, "artifacts")
    mkdir_p(artifacts_path)
    job_name = os.environ.get("JOB_NAME", "defaultjob")
    build_id = os.environ.get("BUILD_ID", "0000-0000-0000-0000")
    remote_job_path = os.path.join(remote_base, job_name)
    remote_build_path = os.path.join(remote_job_path, build_id)
    paths = {
        "build_log": os.path.join(log_path, "build-log.txt"),
        "remote_build_log": os.path.join(remote_build_path, "build-log.txt"),
        "artifacts": artifacts_path,
        "remote_artifacts_path": os.path.join(remote_build_path, "artifacts"),
        "finished": os.path.join(log_path, "finished.json"),
        "started": os.path.join(log_path, "started.json"),
        "remote_build_path": remote_build_path,
        "remote_started": os.path.join(remote_build_path, "started.json"),
        "remote_finished": os.path.join(remote_build_path, "finished.json"),
        "remote_latest_build": os.path.join(remote_job_path,
                                            "latest-build.txt"),
        "latest_build": os.path.join("/tmp", "latest-build.txt"),
    }
    return paths


def upload_file(local, remote):
    if os.path.exists(local):
        call(sh.gsutil, ["-q", "cp", local, remote])


def upload_artifacts(local, remote):
    if os.path.exists(local):
        call(sh.gsutil, ["-q", "cp", "-r", local, remote])


def create_latest_build(path):
    latest_build = os.environ.get("BUILD_ID", "0000-0000-0000-0000")
    with open(path, "w") as f:
        f.write(latest_build)


def create_started(path):
    data = {
        'timestamp': int(time.time()),
        'node': "temp",
    }
    with open(path, "w") as f:
        json.dump(data, f)


def create_finished(path, success=True, meta=None):
    data = {
        'timestamp': int(time.time()),
        'result': 'SUCCESS' if success else 'FAILURE',
        'passed': bool(success),
        'metadata': meta,
    }
    with open(path, "w") as f:
        json.dump(data, f)


def main():
    opts = parse_args()[0]
    log_paths = create_log_paths(opts.log_path, opts.gs)
    logger.info("Log paths: %s", log_paths)
    setup_logging(os.path.join(log_paths["build_log"]))

    logger.info("Waiting for DNS")
    while True:
        try:
            socket.gethostbyname("github.com")
            break
        except socket.error:
            time.sleep(3)

    success = False
    try:
        gcloud_login(opts.service_account)

        create_started(log_paths["started"])
        upload_file(log_paths["started"], log_paths["remote_started"])

        create_latest_build(log_paths["latest_build"])

        logger.info("Clonning job repo: %s on branch %s.", opts.job_repo,
                    opts.job_branch)
        clone_repo(opts.job_repo, opts.job_branch, JOB_REPO_CLONE_DST)
        job_config_file = get_job_config_file(opts.job_config)
        logger.info("Using job config file: %s", job_config_file)
        cluster_name = get_cluster_name()

        # Reset logging format before running civ2
        for handler in logger.handlers:
            handler.setFormatter(logging.Formatter("%(message)s"))

        cmd_args = [
            "civ2.py",
            "--configfile=%s" % job_config_file,
            "--cluster-name=%s" % cluster_name,
            "--log-path=%s" % log_paths["artifacts"]
        ]
        if len(opts.job_args) > 1:
            cmd_args += opts.job_args[1:]

        os.chdir(os.path.join(JOB_REPO_CLONE_DST, "v2"))
        call(sh.python3, cmd_args)

        success = True
    finally:
        create_finished(log_paths["finished"], success)
        upload_file(log_paths["finished"], log_paths["remote_finished"])
        upload_file(log_paths["build_log"], log_paths["remote_build_log"])
        upload_artifacts(log_paths["artifacts"],
                         log_paths["remote_artifacts_path"])
        upload_file(log_paths["latest_build"],
                    log_paths["remote_latest_build"])


if __name__ == "__main__":
    main()
