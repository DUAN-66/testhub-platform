"""Adversarial regression cases for reused-platform trust boundaries."""
import threading
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.users.models import User
from apps.api_testing.models import ApiCollection, ApiProject, ApiRequest, Environment, RequestHistory, AIServiceConfig
from apps.api_testing.engine import RequestBuilder, RunContext
from apps.api_testing.services.http_transport import RestrictedHttpClient
from apps.api_testing.services import ApiExecutionService
from apps.api_testing.models import TestSuite as ApiSuite, TestExecution


@pytest.fixture
def boundary(db):
    owner = User.objects.create_user(username='security-owner', password='test-fixture-password', email='private@example.invalid', phone='fixture-phone')
    outsider = User.objects.create_user(username='security-outsider', password='test-fixture-password')
    project = ApiProject.objects.create(name='private-project', owner=owner)
    client = APIClient()
    client.force_authenticate(outsider)
    return owner, outsider, project, client


@pytest.mark.parametrize('method', ['patch', 'delete'])
def test_other_account_cannot_be_modified(boundary, method):
    owner, _, _, client = boundary
    response = getattr(client, method)(f'/api/auth/users/{owner.pk}/', {'username': 'hijacked'}, format='json')
    assert response.status_code == 404
    assert User.objects.filter(pk=owner.pk, username='security-owner').exists()


@pytest.mark.parametrize('path', ['/api/users/', '/api/api-testing/users/'])
def test_member_directory_does_not_publish_contact_details(boundary, path):
    _, _, _, client = boundary
    response = client.get(path)
    assert response.status_code == 200
    assert 'private@example.invalid' not in str(response.data)
    assert 'fixture-phone' not in str(response.data)


def test_self_edit_cannot_change_account_activation(boundary):
    _, outsider, _, client = boundary
    assert client.patch(f'/api/auth/users/{outsider.pk}/', {'is_active': False}, format='json').status_code == 200
    outsider.refresh_from_db()
    assert outsider.is_active


@override_settings(REGISTRATION_ENABLED=False)
@pytest.mark.parametrize('path', ['/api/auth/register/', '/api/auth/test-register/'])
def test_registration_switch_blocks_account_creation(boundary, path):
    client = APIClient()
    response = client.post(path, {'username': 'unexpected', 'password': '123456', 'password_confirm': '123456'}, format='json')
    expected = (403, 404) if path.endswith('test-register/') else (403,)
    assert response.status_code in expected
    assert not User.objects.filter(username='unexpected').exists()


def test_session_requires_csrf_and_jwt_login_does_not_create_session(boundary):
    owner, _, _, _ = boundary
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(owner)
    response = client.post('/api/api-testing/projects/', {'name': 'csrf-forgery'}, format='json')
    assert response.status_code == 403
    assert not ApiProject.objects.filter(name='csrf-forgery').exists()
    client = APIClient(enforce_csrf_checks=True)
    response = client.post('/api/auth/login/', {'username': owner.username, 'password': 'test-fixture-password'}, format='json')
    assert response.status_code == 200
    assert 'sessionid' not in client.cookies
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert client.patch(f'/api/auth/users/{owner.pk}/', {'first_name': 'JWT'}, format='json').status_code == 200


def test_global_environment_is_private_and_cannot_be_borrowed(boundary):
    owner, outsider, project, client = boundary
    foreign = Environment.objects.create(name='private-env', scope='GLOBAL', created_by=owner, variables={'password': 'fixture-private-value'}, is_active=True)
    own = Environment.objects.create(name='own-env', scope='GLOBAL', created_by=outsider, variables={})
    project.members.add(outsider)
    assert client.get(f'/api/api-testing/environments/{foreign.pk}/').status_code == 404
    assert 'fixture-private-value' not in str(client.get('/api/api-testing/environments/').data)
    response = client.post('/api/api-testing/test-suites/', {'name': 'foreign-env-suite', 'project': project.pk, 'environment': foreign.pk}, format='json')
    assert response.status_code == 400
    request = ApiRequest.objects.create(name='request', created_by=outsider, url='http://127.0.0.1/')
    with patch('apps.api_testing.services.execution.ApiExecutionService.execute_request') as execute:
        assert client.post(f'/api/api-testing/requests/{request.pk}/execute/', {'environment_id': foreign.pk}, format='json').status_code == 400
        execute.assert_not_called()
    assert client.post(f'/api/api-testing/environments/{own.pk}/activate/').status_code == 200
    foreign.refresh_from_db()
    assert foreign.is_active


def test_existing_suite_cannot_borrow_private_environment(boundary):
    owner, outsider, project, client = boundary
    project.members.add(outsider)
    environment = Environment.objects.create(name='owner-global', scope='GLOBAL', created_by=owner, variables={'password': 'private'})
    suite = ApiSuite.objects.create(name='legacy-suite', project=project, environment=environment, created_by=owner)
    with patch('apps.api_testing.tasks.execute_test_suite_task.apply_async') as publish:
        assert client.post(f'/api/api-testing/test-suites/{suite.pk}/execute/').status_code == 400
        publish.assert_not_called()
    assert not TestExecution.objects.filter(test_suite=suite).exists()


def test_worker_rechecks_permission_after_queueing(boundary):
    owner, outsider, project, _ = boundary
    project.members.add(outsider)
    suite = ApiSuite.objects.create(name='queued-suite', project=project, created_by=owner)
    service = ApiExecutionService()
    execution = service.create_suite_execution(suite, outsider)
    project.members.remove(outsider)
    with patch.object(service, 'execute_request') as request:
        with pytest.raises(ValueError, match='无权执行'):
            service.execute_existing_suite(execution.pk)
        request.assert_not_called()


def test_gate_plan_cannot_resolve_another_members_private_environment(boundary):
    from apps.contracts.models import ContractVersion
    owner, outsider, project, client = boundary
    project.members.add(outsider)
    environment = Environment.objects.create(name='private-env', scope='GLOBAL', created_by=owner, variables={'token': 'fixture-private'})
    ApiSuite.objects.create(name='suite', project=project, environment=environment, created_by=owner)
    fixtures = Path(__file__).resolve().parents[3] / 'fixtures' / 'contracts'
    versions = [ContractVersion.objects.create(project=project, name=name, digest=str(index) * 64,
        document=json.loads((fixtures / f'{name}.json').read_text()), created_by=owner)
        for index, name in enumerate(['baseline', 'compatible'])]
    with patch('apps.quality_gates.views.analyze') as analyze:
        response = client.post('/api/v1/quality/plan/', {'baseline_id': str(versions[0].pk), 'candidate_id': str(versions[1].pk)}, format='json')
        assert response.status_code == 400
        assert 'environment' in response.data
        analyze.assert_not_called()


def test_collection_cannot_link_foreign_project_or_parent(boundary):
    owner, outsider, project, client = boundary
    foreign_parent = ApiCollection.objects.create(name='foreign-parent', project=project)
    own_project = ApiProject.objects.create(name='own-project', owner=outsider)
    for payload in [
        {'name': 'injected', 'project': project.pk},
        {'name': 'leaked', 'project': own_project.pk, 'parent': foreign_parent.pk},
    ]:
        assert client.post('/api/api-testing/collections/', payload, format='json').status_code == 400
    parent = ApiCollection.objects.create(name='parent', project=own_project)
    child = ApiCollection.objects.create(name='child', project=own_project, parent=parent)
    assert client.patch(f'/api/api-testing/collections/{parent.pk}/', {'parent': child.pk}, format='json').status_code == 400
    assert client.patch(f'/api/api-testing/collections/{parent.pk}/', {'project': project.pk}, format='json').status_code == 400


def test_project_member_cannot_replace_members_or_delete_project(boundary):
    _, outsider, project, client = boundary
    project.members.add(outsider)
    assert client.patch(f'/api/api-testing/projects/{project.pk}/', {'member_ids': []}, format='json').status_code == 400
    assert client.delete(f'/api/api-testing/projects/{project.pk}/').status_code == 403
    assert ApiProject.objects.filter(pk=project.pk).exists()


def test_execution_history_cannot_be_fabricated_or_rewritten(boundary):
    _, outsider, _, client = boundary
    request = ApiRequest.objects.create(name='history-request', created_by=outsider, url='http://127.0.0.1/')
    history = RequestHistory.objects.create(request=request, executed_by=outsider, request_data={}, status_code=500)
    assert client.patch(f'/api/api-testing/histories/{history.pk}/', {'status_code': 200}, format='json').status_code == 405
    assert client.post('/api/api-testing/histories/', {}, format='json').status_code == 405
    history.refresh_from_db()
    assert history.status_code == 500


def test_ai_key_is_write_only_and_blank_edit_preserves_existing_key(boundary):
    _, outsider, _, client = boundary
    config = AIServiceConfig.objects.create(name='config', service_type='other', role='naming', api_key='test-fixture-api-value', base_url='https://example.invalid', model_name='fixture', created_by=outsider)
    response = client.get(f'/api/api-testing/ai-service-configs/{config.pk}/')
    assert response.status_code == 200
    assert 'api_key' not in response.data
    assert 'test-fixture-api-value' not in str(client.get('/api/api-testing/ai-service-configs/').data)
    assert client.patch(f'/api/api-testing/ai-service-configs/{config.pk}/', {'name': 'updated'}, format='json').status_code == 200
    config.refresh_from_db()
    assert config.api_key == 'test-fixture-api-value'


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'http://user:password@127.0.0.1/',
    'http://169.254.169.254/latest/meta-data/', 'http://127.0.0.1.attacker.invalid/',
    'http://127.0.0.1:99999/', 'http://[invalid/',
])
@override_settings(API_TEST_ALLOWED_HOSTS=['127.0.0.1'])
def test_disallowed_targets_fail_before_network_access(url):
    with patch('apps.api_testing.services.http_transport.requests.Session') as session:
        with pytest.raises(ValueError):
            RestrictedHttpClient().request(method='GET', url=url)
        session.assert_not_called()


@pytest.mark.parametrize('headers', [{'Host': 'metadata.internal'}, {'Proxy-Authorization': 'fixture'}])
@override_settings(API_TEST_ALLOWED_HOSTS=['127.0.0.1'])
def test_header_override_cannot_bypass_target_policy(headers):
    with pytest.raises(ValueError):
        RestrictedHttpClient().request(method='GET', url='http://127.0.0.1/', headers=headers)


@override_settings(API_TEST_ALLOWED_HOSTS=['127.0.0.1'], API_TEST_MAX_RESPONSE_BYTES=3)
def test_response_limit_closes_connection_and_disables_proxies():
    response = MagicMock()
    response.iter_content.return_value = [b'ab', b'cd']
    session = MagicMock()
    session.request.return_value = response
    with patch('apps.api_testing.services.http_transport.requests.Session') as constructor:
        constructor.return_value.__enter__.return_value = session
        with pytest.raises(ValueError, match='Response exceeds'):
            RestrictedHttpClient().request(method='GET', url='http://127.0.0.1/', timeout=1)
    assert session.trust_env is False
    assert session.request.call_args.kwargs['verify'] is True
    assert session.request.call_args.kwargs['allow_redirects'] is False
    response.close.assert_called_once()


@override_settings(API_TEST_ALLOWED_HOSTS=['127.0.0.1'])
def test_real_http_redirect_does_not_contact_destination():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302 if self.path == '/redirect' else 200)
            if self.path == '/redirect':
                self.send_header('Location', '/private')
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = RestrictedHttpClient().request(method='GET', url=f'http://127.0.0.1:{server.server_port}/redirect', timeout=1)
        assert response.status_code == 302
        assert hits == ['/redirect']
        assert response.content == b''
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('timeout', [0, -1, 121, float('nan'), float('inf')])
def test_invalid_timeouts_are_rejected(timeout):
    with pytest.raises(ValueError):
        RequestBuilder().build({'url': 'http://127.0.0.1/', 'timeout': timeout}, RunContext.from_environment({}))


def test_exchange_uses_full_random_code_and_atomic_redemption(boundary):
    owner, _, _, client = boundary
    redis = MagicMock()
    redis.getdel.side_effect = [str(owner.pk), None]
    with patch('apps.users.views.get_redis', return_value=redis):
        created = client.post('/api/auth/exchange-token/', {'action': 'create'}, format='json')
        assert created.status_code == 200
        code = created.data['code']
        assert len(code) == 32
        client.force_authenticate(None)
        assert client.post('/api/auth/exchange-token/', {'action': 'redeem', 'code': code}, format='json').status_code == 200
        assert client.post('/api/auth/exchange-token/', {'action': 'redeem', 'code': code}, format='json').status_code == 400
    assert redis.getdel.call_count == 2
    redis.get.assert_not_called()
    redis.delete.assert_not_called()


@override_settings(CORE_ONLY_MODE=True)
@pytest.mark.parametrize('path', ['/api/ui-automation/', '/api/app-automation/', '/api/perf-testing/',
    '/api/requirement-analysis/', '/api/api-testing/ai-service-configs/', '/api/api-testing/scheduled-tasks/',
    '/api/mcp/', '/api/core/', '/api/monitor/', '/app-automation-reports/private/index.html', '/api/auth/send-register-code/'])
def test_production_core_mode_blocks_optional_modules(boundary, path):
    _, _, _, client = boundary
    assert client.get(path).status_code == 403
    assert client.post(path, {}, format='json').status_code == 403


@override_settings(CORE_ONLY_MODE=True)
def test_core_mode_preserves_auth_execution_and_clickjacking_protection(boundary):
    _, _, _, client = boundary
    response = client.get('/api/api-testing/projects/')
    assert response.status_code == 200
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert client.get('/health/').status_code == 200


def test_core_mode_rejects_optional_websocket_before_routing():
    from backend.asgi import _WebSocketBoundary
    from unittest.mock import AsyncMock
    from asgiref.sync import async_to_sync
    upstream = AsyncMock()
    send = AsyncMock()
    with override_settings(CORE_ONLY_MODE=True):
        async_to_sync(_WebSocketBoundary(upstream))({'type': 'websocket', 'path': '/ws/perf-testing/executions/1/'}, AsyncMock(), send)
    upstream.assert_not_called()
    send.assert_awaited_once_with({'type': 'websocket.close', 'code': 4403})
