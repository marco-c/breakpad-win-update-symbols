#!/bin/env python
#
# Copyright 2016 Mozilla
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''
This script triggers taskcluster tasks to fetch missing symbols from
Microsoft's symbol server and upload them to crash-stats.mozilla.com.
'''

from __future__ import print_function

import argparse
import datetime
import json
import os
import sys
import taskcluster

import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()


def local_file(filename):
    '''
    Return a path to a file next to this script.
    '''
    return os.path.join(os.path.dirname(__file__), filename)


def read_tc_auth():
    '''
    Read taskcluster credentials from taskcluster-auth.json and return them as a dict.
    '''
    return json.load(open(local_file('taskcluster-auth.json'), 'rb'))


def fill_template_property(val, keys):
    if isinstance(val, basestring) and '{' in val:
         return val.format(**keys)
    elif isinstance(val, dict):
        return fill_template_dict(val, keys)
    elif isinstance(val, list):
        return fill_template_list(val, keys)
    return val


def fill_template_list(l, keys):
    return [fill_template_property(v, keys) for v in l]


def fill_template_dict(d, keys):
    for key, val in d.items():
        d[key] = fill_template_property(val, keys)
    return d


def fill_template(template_file, keys):
    '''
    Take the file object template_file, parse it as JSON, and
    interpolate (using str.template) its keys using keys.
    '''
    template = json.load(template_file)
    return fill_template_dict(template, keys)


def format_timedelta(d, **kwargs):
    if kwargs:
        d = d + datetime.timedelta(**kwargs)
    return d.isoformat() + 'Z'


def spawn_task(queue, keys, decision_task_id, template_file):
    task_id = taskcluster.utils.slugId()
    with open(local_file(template_file), 'rb') as template:
        payload = fill_template(template, keys)
        if decision_task_id and not payload.get('dependencies'):
            payload['dependencies'] = [decision_task_id]
        queue.createTask(task_id, payload)
    return task_id


def main():
    parser = argparse.ArgumentParser(
        description='Spawn tasks to fetch missing symbols from Microsoft symbol server')

    args = parser.parse_args()
    decision_task_id = os.environ.get('TASK_ID')
    if decision_task_id:
        task_group_id = decision_task_id
        options = {'baseUrl': 'http://taskcluster/queue/v1/'}
    else:
        task_group_id = taskcluster.utils.slugId()
        options = {'credentials': read_tc_auth()}
    now = datetime.datetime.utcnow()
    keys = {
        'task_group_id': task_group_id,
        'task_created': format_timedelta(now),
        'task_deadline': format_timedelta(now, hours=8),
        'artifacts_expires': format_timedelta(now, days=1),
        'date_index': now.strftime('%Y%m%d%H%M%S'),
    }
    try:
        queue = taskcluster.Queue(options)
        fetch_task_id = spawn_task(queue, keys, decision_task_id, "fetch-task.json")
        keys['fetch_task_id'] = fetch_task_id
        spawn_task(queue, keys, decision_task_id, "upload-task.json")
        print('https://tools.taskcluster.net/task-group-inspector/#/' + task_group_id)
    except taskcluster.exceptions.TaskclusterAuthFailure as e:
        print('TaskclusterAuthFailure: {}'.format(e.body), file=sys.stderr)
        raise


if __name__ == '__main__':
    main()
