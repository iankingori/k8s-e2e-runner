#!/usr/bin/env python3

import sys
import time

import yaml

PROW_CONFIG_PATH = sys.argv[1]
PROW_JOBS_PATH = sys.argv[2]
JOB_NAME = sys.argv[3]

with open(PROW_CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f.read())
with open(PROW_JOBS_PATH, 'r') as f:
    jobs = yaml.safe_load(f.read())

for c in config['presets']:
    if 'preset-test-regex' not in c['labels']:
        continue
    test_focus_regex = [
        e['value'] for e in c['env'] if e['name'] == 'TEST_FOCUS_REGEX'][0]
    test_focus_regex = test_focus_regex.replace('\\\\', '\\')
    test_skip_regex = [
        e['value'] for e in c['env'] if e['name'] == 'TEST_SKIP_REGEX'][0]
    test_skip_regex = test_skip_regex.replace('\\\\', '\\')
    break

for j in jobs['periodics']:
    if j['name'] == JOB_NAME:
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
