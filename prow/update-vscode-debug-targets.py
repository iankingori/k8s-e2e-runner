#!/usr/bin/env python3

# This script parses the Prow config and jobs files to generate the file
# '.vscode/launch.json' in the root of the repository, which contains the
# debugging targets for the Prowjobs.

import json
import os

import yaml

PROW_DIR = os.path.dirname(os.path.realpath(__file__))
VSCODE_DIR = os.path.realpath(os.path.join(PROW_DIR, '..', '.vscode'))
VSCODE_LAUNCH_FILE = os.path.join(VSCODE_DIR, 'launch.json')
PROW_CONFIG_FILE = os.path.join(PROW_DIR, 'config.yaml')
PROW_JOBS_FILE = os.path.join(PROW_DIR, 'jobs/sig-windows-networking.yaml')


def read_yaml_from_file(file_path):
    with open(file_path, 'r') as f:
        return yaml.safe_load(f.read())


def get_launch_config(job_name, job_args):
    return {
        "name": job_name,
        "type": "docker",
        "request": "launch",
        "preLaunchTask": "docker-run: debug",
        "python": {
                "pathMappings": [
                    {
                        "localRoot": "${workspaceFolder}/e2e-runner",
                        "remoteRoot": "/app",
                    },
                ],
            "projectType": "general",
            "args": job_args,
        },
    }


def main():
    jobs = read_yaml_from_file(PROW_JOBS_FILE)

    vscode_launch = {
        "configurations": []
    }
    for j in jobs['periodics']:
        job_args = [
            "run",
            "ci",
            "--quiet",
            *j['spec']['containers'][0]['args'],
        ]
        launch_config = get_launch_config(j['name'], job_args)
        vscode_launch['configurations'].append(launch_config)
    with open(VSCODE_LAUNCH_FILE, 'w') as f:
        json.dump(vscode_launch, f, indent=4)


if __name__ == '__main__':
    main()
