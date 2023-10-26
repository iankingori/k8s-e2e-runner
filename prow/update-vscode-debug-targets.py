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


def get_preset_name(job_name):
    if job_name.startswith('aks-e2e'):
        return 'preset-aks-test-regex'
    return 'preset-flannel-test-regex'


def get_test_regexes(config, preset_name):
    for c in config['presets']:
        if preset_name not in c['labels']:
            continue
        test_focus_regex = [
            e['value'] for e in c['env'] if e['name'] == 'TEST_FOCUS_REGEX'][0]
        test_focus_regex = test_focus_regex.replace('\\\\', '')
        test_skip_regex = [
            e['value'] for e in c['env'] if e['name'] == 'TEST_SKIP_REGEX'][0]
        test_skip_regex = test_skip_regex.replace('\\\\', '')
        return test_focus_regex, test_skip_regex
    return None, None


def get_job_args(container_args, test_focus_regex, test_skip_regex):
    job_args = [
        "run",
        "ci",
        "--quiet",
    ]
    for arg in container_args:
        if '$(TEST_SKIP_REGEX)' in arg:
            arg = arg.replace('$(TEST_SKIP_REGEX)', f"'{test_skip_regex}'")
        if '$(TEST_FOCUS_REGEX)' in arg:
            arg = arg.replace('$(TEST_FOCUS_REGEX)', f"'{test_focus_regex}'")
        job_args.append(arg)
    return job_args


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
    config = read_yaml_from_file(PROW_CONFIG_FILE)
    jobs = read_yaml_from_file(PROW_JOBS_FILE)

    vscode_launch = {
        "configurations": []
    }
    for j in jobs['periodics']:
        preset_name = get_preset_name(j['name'])
        test_focus_regex, test_skip_regex = get_test_regexes(config,
                                                             preset_name)
        job_args = get_job_args(j['spec']['containers'][0]['args'],
                                test_focus_regex,
                                test_skip_regex)
        launch_config = get_launch_config(j['name'], job_args)
        vscode_launch['configurations'].append(launch_config)
    with open(VSCODE_LAUNCH_FILE, 'w') as f:
        json.dump(vscode_launch, f, indent=4)


if __name__ == '__main__':
    main()
