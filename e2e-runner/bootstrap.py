#!/usr/bin/env python3

import errno
import logging
import json
import os
import socket
import time

import configargparse
import sh

logger = logging.getLogger("bootstrap")


def parse_args():
    p = configargparse.get_argument_parser()

    p.add("--k8s-e2e-runner-repo",
          default="https://github.com/e2e-win/k8s-e2e-runner.git",
          help="Repository for the k8s-e2e-runner.")
    p.add("--k8s-e2e-runner-branch", default="master",
          help="Branch for the k8s-e2e-runner repository.")
    p.add("--output-directory", default="/tmp/ci_output",
          help="Local directory with the job logs and artifacts.")
    p.add("--gcloud-service-account",
          help="Service account for gcloud login.")
    p.add("--gcloud-upload-bucket",
          help="Google Cloud bucket used to upload the job artifacts.")
    p.add("job_args", nargs=configargparse.REMAINDER)

    return p.parse_known_args()


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


def call(cmd, args):
    def process_stdout(line):
        logger.info(line.strip())

    def process_stderr(line):
        logger.warning(line.strip())

    proc = cmd(args, _out=process_stdout, _err=process_stderr, _bg=True)
    proc.wait()


def gcloud_login(gcloud_service_account):
    logger.info("Logging in to gcloud.")
    call(sh.gcloud, ["auth", "activate-service-account",
                     "--no-user-output-enabled",
                     "--key-file={}".format(gcloud_service_account)])


def mkdir_p(dir_path):
    try:
        os.mkdir(dir_path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def get_ci_paths(local_base_path, remote_base_path):
    mkdir_p(local_base_path)
    artifacts_path = os.path.join(local_base_path, "artifacts")
    mkdir_p(artifacts_path)
    job_name = os.environ.get("JOB_NAME", "defaultjob")
    build_id = os.environ.get("BUILD_ID", "0000-0000-0000-0000")
    remote_job_path = os.path.join(remote_base_path, job_name)
    remote_build_path = os.path.join(remote_job_path, build_id)
    paths = {
        "build_log": os.path.join(local_base_path, "build-log.txt"),
        "remote_build_log": os.path.join(remote_build_path, "build-log.txt"),
        "artifacts": artifacts_path,
        "remote_artifacts_path": os.path.join(remote_build_path, "artifacts"),
        "finished": os.path.join(local_base_path, "finished.json"),
        "started": os.path.join(local_base_path, "started.json"),
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
    if os.path.exists(local) and len(os.listdir(local)) > 0:
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
    ci_paths = get_ci_paths(opts.output_directory, opts.gcloud_upload_bucket)
    logger.info("CI paths: {}".format(ci_paths))
    setup_logging(os.path.join(ci_paths["build_log"]))

    logger.info("Waiting for DNS")
    while True:
        try:
            socket.gethostbyname("github.com")
            break
        except socket.error:
            time.sleep(3)

    success = True
    try:
        gcloud_login(opts.gcloud_service_account)

        create_started(ci_paths["started"])
        upload_file(ci_paths["started"], ci_paths["remote_started"])

        create_latest_build(ci_paths["latest_build"])

        pip_git_pkg = \
            "git+{0}@{1}#egg=e2e-runner&subdirectory=e2e-runner".format(
                opts.k8s_e2e_runner_repo, opts.k8s_e2e_runner_branch)
        logger.info("Installing the e2e-runner from {}".format(pip_git_pkg))
        call(sh.pip3, ["install", pip_git_pkg])

        # Reset logging format before running the runner CI
        for handler in logger.handlers:
            handler.setFormatter(logging.Formatter("%(message)s"))

        cmd_args = [
            "run", "ci", "--quiet",
            "--artifacts-directory={}".format(ci_paths["artifacts"])
        ]
        if len(opts.job_args) > 1:
            cmd_args += opts.job_args[1:]

        call(sh.e2e_runner, cmd_args)
    except Exception:
        success = False
    finally:
        create_finished(ci_paths["finished"], success)
        upload_file(ci_paths["finished"], ci_paths["remote_finished"])
        upload_file(ci_paths["build_log"], ci_paths["remote_build_log"])
        upload_artifacts(ci_paths["artifacts"],
                         ci_paths["remote_artifacts_path"])
        upload_file(ci_paths["latest_build"], ci_paths["remote_latest_build"])


if __name__ == "__main__":
    main()
