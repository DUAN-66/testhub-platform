"""Real HTTP/MySQL acceptance; exports measured results, never tokens or request bodies."""
import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from quality_gate import GateClient


def items(value):
    return value.get('results', []) if isinstance(value, dict) else value


def wait(client, run):
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        run = client.call('GET', f"/v1/performance/{run['id']}/")
        if run['status'] in {'COMPLETED', 'FAILED'}:
            assert run['status'] == 'COMPLETED', run['error_code']
            return run
        time.sleep(.3)
    raise AssertionError('Performance worker did not finish')


def verify(base_url, password, skip_inventory=False):
    client = GateClient(base_url, 'testhub_demo', password)
    project = next(p for p in items(client.call('GET', '/api-testing/projects/')) if p['name'] == 'PerformanceGate 演示')
    pid = project['id']
    environment = next(e for e in items(client.call('GET', '/api-testing/environments/', params={'project': pid}))
                       if e['project'] == pid)
    variables = environment['variables']
    variables['access_token'] = {'value': client.session.headers['Authorization'].split(' ', 1)[1], 'secret': True}
    client.call('PATCH', f"/api-testing/environments/{environment['id']}/", json={'variables': variables})
    targets = items(client.call('GET', '/api-testing/requests/', params={'project': pid}))
    targets = {r['name']: r for r in targets if r.get('collection') and r['name'] in {'baseline', 'optimized'}}
    path = f'/demo-commerce/projects/{pid}/products/'
    payloads = [client.call('GET', path, params={'strategy': strategy}) for strategy in ['baseline', 'optimized']]
    assert payloads[0] == payloads[1] and payloads[0]['count'] == 24
    workload = {'users': 4, 'iterations': 10, 'timeout_seconds': 3}

    def launch(target, gate=None):
        return wait(client, client.call('POST', '/v1/performance/',
            json={'request_id': target['id'], 'environment_id': environment['id'], 'gate_id': gate, 'workload': workload},
            headers={'Idempotency-Key': str(uuid.uuid4())}))

    baseline = launch(targets['baseline'])
    assert baseline['summary']['max_queries'] == 49 and baseline['summary']['error_rate'] == 0
    versions = client.call('GET', '/v1/contracts/', params={'project': pid})
    versions = {v['name']: v for v in versions}
    reports = []
    candidate = None
    for budget, expected in [(1, 'PASS'), (0, 'BLOCK')]:
        gate = client.call('POST', '/v1/quality/execute/', json={
            'baseline_id': versions['baseline']['id'], 'candidate_id': versions['compatible']['id'],
            'policy': {'max_p95_ms': 10000, 'performance': {'max_p95_ms': 10000, 'min_rps': .01,
                                                         'min_requests': 40, 'max_queries': budget}}},
            headers={'Idempotency-Key': str(uuid.uuid4())})
        missing = client.call('POST', '/v1/quality/evaluate/', json={'run_id': gate['id']})
        assert missing['decision'] == 'BLOCK'
        candidate = launch(targets['optimized'], gate['id'])
        assert candidate['summary']['max_queries'] == 1 and candidate['summary']['error_rate'] == 0
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            executions = [client.call('GET', f'/api-testing/test-executions/{i}/') for i in gate['execution_ids']]
            if all(e['status'] in {'COMPLETED', 'FAILED'} for e in executions):
                break
            time.sleep(.3)
        report = client.call('POST', '/v1/quality/evaluate/', json={'run_id': gate['id']})
        assert report['decision'] == expected and report['metrics']['pass_rate'] == 100, report
        reports.append(report)
    inventory = ({'verified': False, 'reason': 'Explicit SQLite/local skip; requires MySQL CI proof'}
                 if skip_inventory else verify_inventory(client, pid, path))
    result = {'baseline': baseline, 'candidate': candidate, 'reports': reports,
              'sql_queries': {'baseline': 49, 'optimized': 1, 'reduction_percent': 48 / 49 * 100},
              'inventory': inventory,
              'scope': '24-product DEBUG fixture; bounded closed-loop HTTP; not production capacity'}
    assert variables['access_token']['value'] not in json.dumps(result)
    return result


def verify_inventory(client, pid, path):
    # Concurrent stock proof on an unused fixture product; no stock reset.
    products = client.call('GET', path)['products']
    product = next(p for p in products if p['available'] >= 2)
    stock = product['available']
    url = client.base_url + f"/demo-commerce/projects/{pid}/products/{product['id']}/claim/"
    prefix = str(uuid.uuid4())

    def claim(key):
        response = requests.post(url, headers={'Authorization': client.session.headers['Authorization'],
                                              'Idempotency-Key': key}, timeout=20)
        assert response.status_code in {200, 201, 409}, response.status_code
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        repeated = list(pool.map(claim, [prefix] * 8))
    assert sum(status == 201 for status, _ in repeated) == 1
    assert len({data['receipt'] for _, data in repeated}) == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        unique = list(pool.map(claim, [f'{prefix}-{i}' for i in range(stock + 8)]))
    assert sum(status == 201 for status, _ in unique) == stock - 1
    remaining = next(p for p in client.call('GET', path)['products'] if p['id'] == product['id'])['available']
    assert remaining == 0
    return {'verified': True, 'initial_stock': stock, 'repeat_receipts': 1, 'successful_claims': stock, 'remaining': remaining}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--password', required=True)
    parser.add_argument('--output', default='performance-verification.json')
    parser.add_argument('--skip-inventory', action='store_true', help='SQLite/local only; CI must not skip MySQL proof')
    args = parser.parse_args()
    result = verify(args.base_url, args.password, args.skip_inventory)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'sql_queries': result['sql_queries'], 'inventory': result['inventory'],
                      'baseline': result['baseline']['summary'], 'candidate': result['candidate']['summary'],
                      'decisions': [r['decision'] for r in result['reports']]}, ensure_ascii=False))
