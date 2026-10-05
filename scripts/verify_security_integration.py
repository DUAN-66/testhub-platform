"""Verify atomic SSO redemption against a running backend and real Redis."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading

import requests


def verify(base_url, username, password, frontend=False):
    base = base_url.rstrip('/') + '/api/auth'
    login = requests.post(base + '/login/', json={'username': username, 'password': password}, timeout=15)
    login.raise_for_status()
    assert 'sessionid' not in login.cookies
    headers = {'Authorization': 'Bearer ' + login.json()['access']}
    created = requests.post(base + '/exchange-token/', headers=headers, json={'action': 'create'}, timeout=15)
    created.raise_for_status()
    code = created.json()['code']
    assert len(code) == 32
    barrier = threading.Barrier(2)

    def redeem(_):
        barrier.wait(timeout=10)
        response = requests.post(base + '/exchange-token/', json={'action': 'redeem', 'code': code}, timeout=15)
        if response.status_code == 200:
            assert response.json()['user']['username'] == username
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(redeem, range(2)))
    assert statuses == [200, 400], 'Exactly one concurrent redemption must succeed'
    repeated = requests.post(base + '/exchange-token/', json={'action': 'redeem', 'code': code}, timeout=15)
    assert repeated.status_code == 400
    result = {'login_creates_session': False, 'code_length': 32, 'concurrent_redemption_statuses': statuses,
              'repeated_redemption_status': 400}
    if frontend:
        for path in ['/', '/api-testing/interfaces', '/health']:
            page = requests.get(base_url.rstrip('/') + path, timeout=15)
            page.raise_for_status()
            assert page.headers.get('X-Frame-Options') == 'DENY'
            assert page.headers.get('X-Content-Type-Options') == 'nosniff'
            assert "frame-ancestors 'none'" in page.headers.get('Content-Security-Policy', '')
        result['frontend_security_headers_verified'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--username', default='testhub_demo')
    parser.add_argument('--password', default=os.environ.get('TESTHUB_PASSWORD'))
    parser.add_argument('--output', default='security-integration.json')
    parser.add_argument('--frontend', action='store_true', help='Also validate Nginx HTML and health response headers')
    args = parser.parse_args()
    if not args.password:
        parser.error('Set TESTHUB_PASSWORD or provide --password for the isolated demo')
    result = verify(args.base_url, args.username, args.password, args.frontend)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
