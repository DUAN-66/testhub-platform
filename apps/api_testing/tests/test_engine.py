import json

import pytest

from apps.api_testing.engine import (
    ApiRunner,
    AssertionEngine,
    ExtractorEngine,
    RequestBuilder,
    RunContext,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, headers=None, cookies=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {'content-type': 'application/json'}
        self.cookies = cookies or {}

    def json(self):
        if self._payload is None:
            raise ValueError('not json')
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


def test_context_normalizes_renders_and_masks_secrets():
    context = RunContext.from_environment(
        {
            'base_url': {'currentValue': 'https://api.example.com'},
            'tenant': {'initialValue': 'qa'},
            'api_token': {'value': 'secret-value', 'type': 'secret'},
        }
    )

    rendered = context.render(
        {
            'url': '{{base_url}}/{{tenant}}',
            'headers': ['Bearer {{api_token}}'],
            'unknown': '{{missing}}',
        }
    )

    assert rendered['url'] == 'https://api.example.com/qa'
    assert rendered['headers'] == ['Bearer secret-value']
    assert rendered['unknown'] == '{{missing}}'
    assert context.snapshot()['api_token'] == '******'


def test_request_builder_supports_legacy_and_list_key_values():
    context = RunContext.from_environment({'base_url': 'https://api.example.com', 'token': 'abc'})

    spec = RequestBuilder().build(
        {
            'method': 'post',
            'url': '{{base_url}}/orders',
            'headers': [
                {'key': 'X-Tenant', 'value': 'qa', 'enabled': True},
                {'key': 'X-Disabled', 'value': 'no', 'enabled': False},
            ],
            'params': {'page': 1},
            'auth': {'type': 'bearer', 'token': '{{token}}'},
            'body': {'type': 'json', 'data': {'owner': '{{token}}'}},
        },
        context,
    )

    assert spec.method == 'POST'
    assert spec.url == 'https://api.example.com/orders'
    assert spec.headers == {'X-Tenant': 'qa', 'Authorization': 'Bearer abc'}
    assert spec.params == {'page': 1}
    assert spec.json_body == {'owner': 'abc'}


def test_extractor_engine_updates_shared_context():
    context = RunContext()
    response = FakeResponse(
        payload={'data': {'token': 'jwt-1'}},
        headers={'X-Request-ID': 'req-1'},
        cookies={'session': 'cookie-1'},
    )

    results = ExtractorEngine().extract(
        response,
        [
            {'name': 'access_token', 'source': 'json_path', 'expression': '$.data.token', 'secret': True},
            {'name': 'request_id', 'source': 'header', 'expression': 'X-Request-ID'},
            {'name': 'session', 'source': 'cookie', 'expression': 'session'},
        ],
        context,
    )

    assert all(item.success for item in results)
    assert context.variables['access_token'] == 'jwt-1'
    assert context.variables['request_id'] == 'req-1'
    assert results[0].as_dict()['value'] == '******'


def test_assertion_engine_supports_schema_jsonpath_and_comparison():
    response = FakeResponse(payload={'data': {'count': 3}})
    rules = [
        {'type': 'status_code', 'expected': 200},
        {'type': 'response_time', 'operator': 'lt', 'expected': 100},
        {'type': 'json_path', 'expression': '$.data.count', 'operator': 'gte', 'expected': 2},
        {
            'type': 'json_schema',
            'schema': {
                'type': 'object',
                'required': ['data'],
                'properties': {'data': {'type': 'object'}},
            },
        },
    ]

    results = AssertionEngine().evaluate(response, rules, response_time_ms=12.5)

    assert all(item.passed for item in results)


def test_runner_shares_extracted_token_with_next_request():
    client = FakeClient(
        [
            FakeResponse(payload={'token': 'jwt-1'}),
            FakeResponse(payload={'user': {'id': 7}}),
        ]
    )
    clock = iter([0.0, 0.01, 1.0, 1.02])
    runner = ApiRunner(http_client=client, clock=lambda: next(clock))
    context = RunContext.from_environment({'base_url': 'https://api.example.com'})

    login = runner.run(
        {'method': 'POST', 'url': '{{base_url}}/login', 'body': {'type': 'json', 'data': {}}},
        context,
        assertions=[{'type': 'status_code', 'expected': 200}],
        extractors=[
            {'name': 'access_token', 'source': 'json_path', 'expression': '$.token', 'required': True}
        ],
    )
    profile = runner.run(
        {
            'method': 'GET',
            'url': '{{base_url}}/profile',
            'headers': {'Authorization': 'Bearer {{access_token}}'},
        },
        context,
        assertions=[{'type': 'json_path', 'expression': '$.user.id', 'expected': 7}],
    )

    assert login.passed is True
    assert profile.passed is True
    assert client.calls[1]['headers']['Authorization'] == 'Bearer jwt-1'
    assert profile.response_time_ms == pytest.approx(20.0)


def test_required_extractor_failure_fails_run_without_crashing():
    client = FakeClient([FakeResponse(payload={'data': {}})])
    clock = iter([0.0, 0.01])
    result = ApiRunner(http_client=client, clock=lambda: next(clock)).run(
        {'method': 'GET', 'url': 'https://api.example.com'},
        RunContext(),
        extractors=[
            {'name': 'token', 'source': 'json_path', 'expression': '$.data.token', 'required': True}
        ],
    )

    assert result.passed is False
    assert result.error is None
    assert result.extractions[0].success is False
