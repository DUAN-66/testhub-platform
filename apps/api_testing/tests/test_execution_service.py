import pytest

from apps.api_testing.engine import ApiRunner
from apps.api_testing.models import (
    ApiProject,
    ApiRequest,
    Environment,
    RequestHistory,
    TestSuite as ApiTestSuite,
    TestSuiteRequest as ApiTestSuiteRequest,
)
from apps.api_testing.services import ApiExecutionService
from apps.users.models import User

from .test_engine import FakeClient, FakeResponse


@pytest.mark.django_db
def test_suite_service_shares_context_and_persists_redacted_history():
    user = User.objects.create_user(username='runner', password='test-pass')
    project = ApiProject.objects.create(
        name='API project',
        project_type='HTTP',
        status='IN_PROGRESS',
        owner=user,
    )
    environment = Environment.objects.create(
        name='test',
        scope='LOCAL',
        variables={'base_url': 'https://api.example.com'},
        project=project,
        created_by=user,
    )
    login = ApiRequest.objects.create(
        name='login',
        method='POST',
        url='{{base_url}}/login',
        body={'type': 'json', 'data': {}},
        extractors=[
            {
                'name': 'access_token',
                'source': 'json_path',
                'expression': '$.token',
                'required': True,
                'secret': True,
            }
        ],
        assertions=[{'type': 'status_code', 'expected': 200}],
        created_by=user,
    )
    profile = ApiRequest.objects.create(
        name='profile',
        method='GET',
        url='{{base_url}}/profile',
        headers={'Authorization': 'Bearer {{access_token}}'},
        assertions=[{'type': 'json_path', 'expression': '$.user.id', 'expected': 7}],
        created_by=user,
    )
    suite = ApiTestSuite.objects.create(
        project=project,
        name='login flow',
        environment=environment,
        created_by=user,
    )
    ApiTestSuiteRequest.objects.create(test_suite=suite, request=login, order=1)
    ApiTestSuiteRequest.objects.create(test_suite=suite, request=profile, order=2)

    client = FakeClient(
        [
            FakeResponse(payload={'token': 'jwt-secret'}),
            FakeResponse(payload={'user': {'id': 7}}),
        ]
    )
    clock = iter([0.0, 0.01, 1.0, 1.02])
    service = ApiExecutionService(
        runner=ApiRunner(http_client=client, clock=lambda: next(clock))
    )

    result = service.execute_suite(suite, environment, user)

    assert result['success'] is True
    assert result['passed_count'] == 2
    assert result['failed_count'] == 0
    assert result['context']['access_token'] == '******'
    assert client.calls[1]['headers']['Authorization'] == 'Bearer jwt-secret'
    assert RequestHistory.objects.count() == 2
    profile_history = RequestHistory.objects.get(request=profile)
    assert profile_history.request_data['headers']['Authorization'] == '******'
