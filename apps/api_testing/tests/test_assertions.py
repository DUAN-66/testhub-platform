import json

import pytest
from requests import Response

from apps.api_testing.utils import execute_assertions


def make_response(*, status=200, payload=None, text=None, headers=None):
    response = Response()
    response.status_code = status
    response.headers.update(headers or {})
    if payload is not None:
        response._content = json.dumps(payload).encode('utf-8')
        response.headers.setdefault('content-type', 'application/json')
    else:
        response._content = (text or '').encode('utf-8')
    response.encoding = 'utf-8'
    return response


@pytest.mark.parametrize(
    ('assertion', 'response', 'expected_passed'),
    [
        ({'type': 'status_code', 'expected': 201}, make_response(status=201), True),
        ({'type': 'contains', 'expected': 'ready'}, make_response(text='service ready'), True),
        ({'type': 'equals', 'expected': 'ok'}, make_response(text=' ok '), True),
        (
            {'type': 'header', 'header_name': 'x-trace-id', 'expected_value': 'trace-1'},
            make_response(headers={'x-trace-id': 'trace-1'}),
            True,
        ),
        (
            {'type': 'json_path', 'json_path': '$.data.id', 'expected': 42},
            make_response(payload={'data': {'id': 42}}),
            True,
        ),
    ],
)
def test_execute_assertions_supported_types(assertion, response, expected_passed):
    result = execute_assertions(response, [assertion])[0]

    assert result['passed'] is expected_passed
    assert result['error'] is None


def test_json_path_reports_non_json_response():
    response = make_response(text='<html>bad gateway</html>', headers={'content-type': 'text/html'})

    result = execute_assertions(
        response,
        [{'type': 'json_path', 'json_path': '$.data.id', 'expected': 42}],
    )[0]

    assert result['passed'] is False
    assert '响应不是JSON格式' in result['error']


def test_unknown_assertion_type_fails_closed():
    result = execute_assertions(
        make_response(),
        [{'type': 'not_registered', 'expected': 'anything'}],
    )[0]

    assert result['passed'] is False
    assert result['actual'] is None
