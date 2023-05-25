#!/usr/bin/env python3

# This script parses the Prow config and jobs files to generate the
# arguments for the "e2e-runner run ci" CLI call.
# This is useful for debugging the E2E runner locally.

import argparse
import time

import yaml


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--job-name',
        required=True, type=str, help='Name of the job to parse')
    parser.add_argument(
        '--prow-config-path',
        required=True, type=str, help='Path to Prow config file')
    parser.add_argument(
        '--prow-jobs-path',
        required=True, type=str, help='Path to Prow jobs file')
    return parser.parse_args()


def get_prow_config(args):
    with open(args.prow_config_path, 'r') as f:
        return yaml.safe_load(f.read())


def get_prow_jobs(args):
    with open(args.prow_jobs_path, 'r') as f:
        return yaml.safe_load(f.read())


def main():
    args = parse_args()
    config = get_prow_config(args)
    jobs = get_prow_jobs(args)

    preset_name = 'preset-flannel-test-regex'
    if args.job_name.startswith('aks-e2e'):
        preset_name = 'preset-aks-test-regex'

    for c in config['presets']:
        if preset_name not in c['labels']:
            continue
        test_focus_regex = [
            e['value'] for e in c['env'] if e['name'] == 'TEST_FOCUS_REGEX'][0]
        test_focus_regex = test_focus_regex.replace('\\\\', '\\')
        test_skip_regex = [
            e['value'] for e in c['env'] if e['name'] == 'TEST_SKIP_REGEX'][0]
        test_skip_regex = test_skip_regex.replace('\\\\', '\\')
        break

    for j in jobs['periodics']:
        if j['name'] == args.job_name:
            job_args = j['spec']['containers'][0]['args']
            break

    for arg in job_args:
        if '$(TEST_SKIP_REGEX)' in arg:
            arg = arg.replace('$(TEST_SKIP_REGEX)', test_skip_regex)
        if '$(TEST_FOCUS_REGEX)' in arg:
            arg = arg.replace('$(TEST_FOCUS_REGEX)', test_focus_regex)
        if '$(BUILD_ID)' in arg:
            arg = arg.replace('$(BUILD_ID)', str(int(time.time())))
        print(arg)


if __name__ == '__main__':
    main()
