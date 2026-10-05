"""CI client. Exit 0=PASS, 2=BLOCK, 3=service/configuration error.

Imports contracts, binds a fresh idempotent run, waits for terminal evidence and
exports its persisted report. Credentials come from environment variables.
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests


class GateClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip('/') + '/api'
        self.session = requests.Session()
        auth = self.call('POST', '/auth/login/', json={'username': username, 'password': password})
        self.session.headers['Authorization'] = 'Bearer ' + auth['access']

    def call(self, method, path, **kwargs):
        response = self.session.request(method, self.base_url + path, timeout=15, **kwargs)
        response.raise_for_status()
        return response.json()

    def run(self, project, baseline, candidate, policy=None, timeout=90, key=None):
        versions = []
        for name, document in [('baseline', baseline), ('candidate', candidate)]:
            versions.append(self.call('POST', '/v1/contracts/', json={'project': project, 'name': name, 'document': document}))
        payload = {'baseline_id': versions[0]['id'], 'candidate_id': versions[1]['id'], 'policy': policy or {}}
        run = self.call('POST', '/v1/quality/execute/', json=payload,
                        headers={'Idempotency-Key': key or str(uuid.uuid4())})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.call('GET', f"/v1/quality/{run['id']}/run/")
            if run['state'] == 'ERROR':
                break
            if run['state'] == 'READY':
                executions = [self.call('GET', f'/api-testing/test-executions/{identifier}/')
                              for identifier in run['execution_ids']]
                if all(e['status'] in {'COMPLETED', 'FAILED', 'CANCELLED'} for e in executions):
                    break
            time.sleep(.3)
        # Timeout produces a persisted BLOCK report, never a synthetic PASS.
        return self.call('POST', '/v1/quality/evaluate/', json={'run_id': run['id']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--project', type=int, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--max-p95-ms', type=float, default=1000)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--idempotency-key')
    parser.add_argument('--output', type=Path, default=Path('gate-report.json'))
    args = parser.parse_args()
    try:
        client = GateClient(args.base_url, os.environ.get('TESTHUB_USERNAME', 'testhub_demo'), os.environ['TESTHUB_PASSWORD'])
        report = client.run(args.project, args.baseline.read_text(encoding='utf-8'), args.candidate.read_text(encoding='utf-8'),
                            {'max_p95_ms': args.max_p95_ms}, args.timeout, args.idempotency_key)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'decision': report['decision'], 'report_id': report['id'], 'metrics': report['metrics']}))
        return 0 if report['decision'] == 'PASS' else 2
    except (requests.RequestException, OSError, KeyError, ValueError):
        print('Quality gate failed: check connection, configuration and credentials.', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
