"""Verify a running HTTP backend and separate Celery worker using demo assets."""
import argparse
import json
import time
from pathlib import Path

import requests


def verify(base_url, username, password):
    client = requests.Session()

    def call(method, path, **kwargs):
        response = client.request(method, base_url + '/api' + path, timeout=15, **kwargs)
        response.raise_for_status()
        return response.status_code, response.json()

    _, auth = call('POST', '/auth/login/', json={'username': username, 'password': password})
    client.headers['Authorization'] = 'Bearer ' + auth['access']
    _, projects = call('GET', '/api-testing/projects/')
    projects = projects.get('results', []) if isinstance(projects, dict) else projects
    project = next(item for item in projects if item['name'] == 'TestHub 二开演示')
    _, suites = call('GET', f"/api-testing/test-suites/?project={project['id']}")
    suites = suites.get('results', []) if isinstance(suites, dict) else suites
    by_name = {item['name']: item for item in suites}
    evidence = []

    def wait_execution(execution_id, predicate, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, detail = call('GET', f'/api-testing/test-executions/{execution_id}/')
            _, logs = call('GET', f'/api-testing/test-executions/{execution_id}/logs/')
            if predicate(detail, logs['logs']):
                return detail, logs['logs']
            time.sleep(0.2)
        raise AssertionError(f'Execution {execution_id} did not reach the expected state')

    for name, expected in [('01 登录关联成功', 'COMPLETED'), ('02 断言失败', 'FAILED')]:
        start = time.monotonic()
        code, run = call('POST', f"/api-testing/test-suites/{by_name[name]['id']}/execute/")
        elapsed = time.monotonic() - start
        assert code == 202
        result, logs = wait_execution(run['id'], lambda detail, _: detail['status'] in {'COMPLETED', 'FAILED'})
        assert result['status'] == expected, result
        assert result['progress'] == 100
        assert result['total_requests'] == 2
        assert 'demo-session-token' not in json.dumps(result)
        assert [item['sequence'] for item in logs] == list(range(1, len(logs) + 1))
        evidence.append({'scenario': name, 'execution_id': run['id'], 'status': expected,
                         'submit_seconds': round(elapsed, 3), 'passed': result['passed_requests'],
                         'failed': result['failed_requests'], 'log_count': len(logs)})

    start = time.monotonic()
    code, run = call('POST', f"/api-testing/test-suites/{by_name['03 运行中取消']['id']}/execute/")
    elapsed = time.monotonic() - start
    assert code == 202 and elapsed < 4, 'Submission blocked on the 6-second HTTP request; use a separate worker'
    wait_execution(run['id'], lambda detail, logs: detail['status'] == 'RUNNING' and any(item['event'] == 'REQUEST_STARTED' for item in logs))
    call('POST', f"/api-testing/test-executions/{run['id']}/cancel/")
    result, logs = wait_execution(run['id'], lambda detail, logs: len(detail['results']) == 1 and any(item['event'] == 'EXECUTION_CANCELLED' for item in logs))
    assert result['status'] == 'CANCELLED'
    assert len(result['results']) == 1
    assert sum(item['event'] == 'REQUEST_STARTED' for item in logs) == 1
    evidence.append({'scenario': '03 运行中取消', 'execution_id': run['id'], 'status': result['status'],
                     'submit_seconds': round(elapsed, 3), 'executed_requests': 1, 'remaining_requests_skipped': True})
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--username', default='testhub_demo')
    parser.add_argument('--password', required=True)
    parser.add_argument('--output', default='docs/secondary-development/demo-verification.json')
    args = parser.parse_args()
    result = verify(args.base_url, args.username, args.password)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))
