import json
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.api_testing.engine import ApiRunner
from apps.api_testing.models import ApiProject, ApiRequest, Environment, RequestHistory, TestExecution, TestSuite as ApiSuite, TestSuiteRequest as SuiteRequest
from apps.api_testing.serializers import RequestHistorySerializer
from apps.api_testing.services import ApiExecutionService, ExecutionStateMachine
from apps.users.models import User
from scripts.demo_api import DemoHandler
from .test_engine import FakeClient, FakeResponse


@pytest.fixture
def flow(db):
    user = User.objects.create_user(username='flow-owner', password='test-pass')
    project = ApiProject.objects.create(name='flow-project', owner=user)
    env = Environment.objects.create(name='env', scope='LOCAL', project=project, created_by=user, variables={})
    suite = ApiSuite.objects.create(name='flow-suite', project=project, environment=env, created_by=user)
    return user, project, env, suite


def test_real_http_login_extraction_profile_and_history(flow):
    user, project, env, suite = flow
    server = ThreadingHTTPServer(('127.0.0.1', 0), DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env.variables = {'base_url': f'http://127.0.0.1:{server.server_port}'}
        env.save()
        login = ApiRequest.objects.create(name='login', method='POST', url='{{base_url}}/login', created_by=user,
            extractors=[{'name': 'access_token', 'expression': '$.token', 'required': True}],
            assertions=[{'type': 'status_code', 'expected': 200}])
        profile = ApiRequest.objects.create(name='profile', method='GET', url='{{base_url}}/profile', created_by=user,
            headers={'Authorization': 'Bearer {{access_token}}'},
            assertions=[{'type': 'json_path', 'expression': '$.user.id', 'expected': 7}])
        SuiteRequest.objects.create(test_suite=suite, request=login, order=0)
        SuiteRequest.objects.create(test_suite=suite, request=profile, order=1)
        client = APIClient()
        client.force_authenticate(user)
        response = client.post(f'/api/api-testing/test-suites/{suite.id}/execute/')
        assert response.status_code == 202
        execution = TestExecution.objects.get(pk=response.data['id'])
        assert execution.status == 'COMPLETED'
        assert execution.passed_requests == 2
        assert execution.progress == 100
        assert RequestHistory.objects.count() == 2
        for history in RequestHistory.objects.all():
            assert 'demo-session-token' not in json.dumps(RequestHistorySerializer(history).data)
        assert 'demo-session-token' not in json.dumps(response.data)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_assertion_failure_finishes_at_100_percent(flow):
    user, project, env, suite = flow
    request = ApiRequest.objects.create(name='wrong-status', method='GET', url='http://example.invalid', created_by=user,
        assertions=[{'type': 'status_code', 'expected': 201}])
    SuiteRequest.objects.create(test_suite=suite, request=request)
    service = ApiExecutionService(runner=ApiRunner(http_client=FakeClient([FakeResponse(payload={})])))
    result = service.execute_suite(suite, env, user)
    execution = TestExecution.objects.get(pk=result['execution_id'])
    assert execution.status == 'FAILED'
    assert execution.progress == 100
    assert execution.failed_requests == 1


def test_cancel_during_request_stops_remaining_steps(flow):
    user, project, env, suite = flow
    for index in range(2):
        request = ApiRequest.objects.create(name=f'step-{index}', method='GET', url='http://example.invalid', created_by=user)
        SuiteRequest.objects.create(test_suite=suite, request=request, order=index)
    service = ApiExecutionService()
    execution = service.create_suite_execution(suite, user)

    def cancel_on_request(*args, **kwargs):
        ExecutionStateMachine.transition(execution.id, 'CANCELLED')
        return {'passed': True, 'request_data': {}, 'status_code': 200, 'response_time': 1,
                'error': '', 'assertions_results': [], 'extractions_results': []}

    with patch.object(service, 'execute_request', side_effect=cancel_on_request) as execute:
        result = service.execute_existing_suite(execution.id)
    assert result['cancelled'] is True
    assert execute.call_count == 1
    execution.refresh_from_db()
    assert execution.status == 'CANCELLED'
    assert len(execution.results) == 1


def test_literal_secret_redaction_in_assertions_errors_and_nested_history(flow):
    user, project, env, suite = flow
    request = ApiRequest.objects.create(name='secret', method='POST', url='http://example.invalid', created_by=user,
        body={'type': 'json', 'data': {'password': 'literal-private-password'}},
        assertions=[{'type': 'contains', 'expected': 'literal-private-password'}])
    service = ApiExecutionService(runner=ApiRunner(http_client=FakeClient([
        FakeResponse(payload={'echo': 'literal-private-password'})])))
    result = service.execute_request(request, env, user)
    assert result['passed'] is True
    assert 'literal-private-password' not in json.dumps(result)
    history = RequestHistory.objects.get(pk=result['history_id'])
    assert 'literal-private-password' not in json.dumps(RequestHistorySerializer(history).data)


def test_suite_rules_validation_and_cross_project_resources(flow):
    user, project, env, suite = flow
    request = ApiRequest.objects.create(name='request', method='GET', url='http://example.invalid', created_by=user)
    step = SuiteRequest.objects.create(test_suite=suite, request=request)
    client = APIClient()
    client.force_authenticate(user)
    assert client.patch(f'/api/api-testing/test-suite-requests/{step.id}/', {'assertions': {}}, format='json').status_code == 400
    other_user = User.objects.create_user(username='another-owner', password='test-pass')
    other_project = ApiProject.objects.create(name='other-project', owner=other_user)
    response = client.post('/api/api-testing/test-suites/', {'name': 'forbidden', 'project': other_project.id}, format='json')
    assert response.status_code == 400
