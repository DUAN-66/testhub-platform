"""Verify worker events cross Redis, Daphne and the optional Nginx proxy."""
import argparse
from contextlib import closing
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
import websocket


def verify(base_url, password):
    client = requests.Session()

    def call(method, path, **kwargs):
        response = client.request(method, base_url + '/api' + path, timeout=15, **kwargs)
        response.raise_for_status()
        return response.json()

    auth = call('POST', '/auth/login/', json={'username': 'testhub_demo', 'password': password})
    client.headers['Authorization'] = 'Bearer ' + auth['access']
    suites = call('GET', '/api-testing/test-suites/')
    suites = suites.get('results', []) if isinstance(suites, dict) else suites
    suite = next(item for item in suites if item['name'] == '03 运行中取消')
    run = call('POST', f"/api-testing/test-suites/{suite['id']}/execute/")
    execution_path = f"/api-testing/test-executions/{run['id']}/"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        logs = call('GET', execution_path + 'logs/')['logs']
        if any(item['event'] == 'REQUEST_STARTED' for item in logs):
            break
        time.sleep(0.1)
    else:
        raise AssertionError('Worker did not start the slow request')
    ticket = call('POST', execution_path + 'realtime-ticket/')
    parsed = urlsplit(base_url)
    ws_url = urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', parsed.netloc, '', '', '')) + ticket['websocket_path']
    received = []
    with closing(websocket.create_connection(ws_url, timeout=15, http_no_proxy=['127.0.0.1', 'localhost'])) as socket:
        snapshot = json.loads(socket.recv())
        assert snapshot['type'] == 'execution_snapshot'
        socket.send(json.dumps({'action': 'ping'}))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            message = json.loads(socket.recv())
            if message['type'] == 'pong':
                break
        else:
            raise AssertionError('WebSocket heartbeat did not respond')
        call('POST', execution_path + 'cancel/')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            message = json.loads(socket.recv())
            assert 'demo-session-token' not in json.dumps(message)
            if message['type'] == 'execution_event':
                received.append(message['event'])
                if message['event'] == 'EXECUTION_CANCELLED':
                    break
        else:
            raise AssertionError('Worker cancellation event was not received over WebSocket')
    result = call('GET', execution_path)
    assert result['status'] == 'CANCELLED' and len(result['results']) == 1
    return {'execution_id': run['id'], 'snapshot_received': True, 'heartbeat_received': True,
            'worker_cancellation_received': True, 'events': received, 'status': result['status']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:18080')
    parser.add_argument('--password', required=True)
    parser.add_argument('--output', default='docs/secondary-development/realtime-verification.json')
    args = parser.parse_args()
    evidence = verify(args.base_url, args.password)
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))
