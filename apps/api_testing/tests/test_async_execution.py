from unittest.mock import patch

import pytest
from django.core import signing
from rest_framework.test import APIClient

from apps.api_testing.models import ApiProject, TestExecution, TestSuite as ApiTestSuite
from apps.api_testing.services import (
    ApiExecutionService,
    ExecutionStateMachine,
    InvalidExecutionTransition,
    dispatch_test_suite,
)
from apps.users.models import User
from apps.api_testing.tasks import execute_test_suite_task


@pytest.fixture
def suite(db):
    user = User.objects.create_user(username='async-runner', password='test-pass')
    project = ApiProject.objects.create(
        name='Async API project',
        project_type='HTTP',
        status='IN_PROGRESS',
        owner=user,
    )
    test_suite = ApiTestSuite.objects.create(
        project=project,
        name='empty suite',
        created_by=user,
    )
    return user, test_suite


@pytest.mark.django_db
def test_state_machine_enforces_transitions_and_writes_ordered_logs(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)

    ExecutionStateMachine.transition(execution.id, 'QUEUED')
    ExecutionStateMachine.transition(execution.id, 'RUNNING')
    ExecutionStateMachine.transition(execution.id, 'COMPLETED')

    execution.refresh_from_db()
    assert execution.status == 'COMPLETED'
    assert execution.progress == 100
    assert execution.state_version == 3
    assert list(execution.logs.values_list('sequence', flat=True)) == [1, 2, 3, 4]

    with pytest.raises(InvalidExecutionTransition):
        ExecutionStateMachine.transition(execution.id, 'RUNNING')


@pytest.mark.django_db
def test_dispatch_persists_task_id_before_celery_publish(suite):
    user, test_suite = suite

    with patch('apps.api_testing.tasks.execute_test_suite_task.apply_async') as apply_async:
        execution = dispatch_test_suite(test_suite, user)

    assert execution.status == 'QUEUED'
    assert execution.celery_task_id
    apply_async.assert_called_once_with(
        args=[execution.id],
        task_id=execution.celery_task_id,
    )


@pytest.mark.django_db
def test_existing_execution_completes_and_exposes_progress_logs(suite):
    user, test_suite = suite
    service = ApiExecutionService()
    execution = service.create_suite_execution(test_suite, user)
    ExecutionStateMachine.transition(execution.id, 'QUEUED')

    result = service.execute_existing_suite(execution.id)

    execution.refresh_from_db()
    assert result['success'] is True
    assert execution.status == 'COMPLETED'
    assert execution.progress == 100
    assert execution.start_time is not None
    assert execution.end_time is not None
    assert execution.logs.filter(event='STATE_CHANGED').count() == 3


@pytest.mark.django_db
def test_cancelled_execution_cannot_be_started(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    ExecutionStateMachine.transition(execution.id, 'QUEUED')
    ExecutionStateMachine.transition(execution.id, 'CANCELLED')

    with pytest.raises(InvalidExecutionTransition):
        ApiExecutionService().execute_existing_suite(execution.id)


@pytest.mark.django_db
def test_execution_http_contract_for_queue_logs_ticket_and_cancel(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    client = APIClient()
    client.force_authenticate(user)

    with patch('apps.api_testing.views.dispatch_test_suite', return_value=execution):
        queued = client.post(
            f'/api/api-testing/test-suites/{test_suite.id}/execute/',
            {},
            format='json',
        )
    assert queued.status_code == 202

    logs = client.get(
        f'/api/api-testing/test-executions/{execution.id}/logs/?after=0&limit=20'
    )
    assert logs.status_code == 200
    assert logs.data['logs'][0]['event'] == 'EXECUTION_CREATED'

    ticket_response = client.post(
        f'/api/api-testing/test-executions/{execution.id}/realtime-ticket/'
    )
    assert ticket_response.status_code == 200
    payload = signing.loads(
        ticket_response.data['ticket'],
        salt='api-testing-execution-ws',
        max_age=60,
    )
    assert payload == {'execution_id': execution.id, 'user_id': user.id}

    cancelled = client.post(
        f'/api/api-testing/test-executions/{execution.id}/cancel/'
    )
    assert cancelled.status_code == 200
    assert cancelled.data['status'] == 'CANCELLED'


@pytest.mark.django_db
def test_worker_duplicate_delivery_never_executes_again(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    execution.celery_task_id = 'stable-task'
    execution.save()
    first = execute_test_suite_task.apply(args=[execution.id], task_id='stable-task').get()
    second = execute_test_suite_task.apply(args=[execution.id], task_id='stable-task').get()
    assert first['success'] is True
    assert second['skipped'] is True
    execution.refresh_from_db()
    assert execution.logs.filter(data__status='RUNNING').count() == 1


@pytest.mark.django_db
def test_worker_rejects_another_task_id(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    execution.celery_task_id = 'expected'
    execution.save()
    result = execute_test_suite_task.apply(args=[execution.id], task_id='unexpected').get()
    assert result['error'] == 'task_id_mismatch'
    execution.refresh_from_db()
    assert execution.status == 'PENDING'
    assert execution.celery_task_id == 'expected'


@pytest.mark.django_db
def test_atomic_claim_rejects_running_execution(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    ExecutionStateMachine.transition(execution.id, 'RUNNING')
    with pytest.raises(InvalidExecutionTransition):
        ExecutionStateMachine.transition(execution.id, 'RUNNING', expected_states=frozenset({'QUEUED'}))


@pytest.mark.django_db
def test_broker_failure_is_persisted(suite):
    user, test_suite = suite
    with patch('apps.api_testing.tasks.execute_test_suite_task.apply_async', side_effect=RuntimeError('broker unavailable')):
        with pytest.raises(RuntimeError):
            dispatch_test_suite(test_suite, user)
    execution = TestExecution.objects.get(test_suite=test_suite)
    assert execution.status == 'FAILED'
    assert 'broker unavailable' in execution.error_message


@pytest.mark.django_db
def test_execution_apis_enforce_project_membership(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    outsider = User.objects.create_user(username='outsider', password='test-pass')
    client = APIClient()
    client.force_authenticate(outsider)
    base = f'/api/api-testing/test-executions/{execution.id}/'
    for path in [base, base + 'logs/']:
        assert client.get(path).status_code == 404
    for path in [base + 'cancel/', base + 'realtime-ticket/']:
        assert client.post(path).status_code == 404
    assert client.post(f'/api/api-testing/test-suites/{test_suite.id}/execute/').status_code == 404


@pytest.mark.django_db
def test_logs_cursor_validation_and_terminal_cancellation(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    client = APIClient()
    client.force_authenticate(user)
    base = f'/api/api-testing/test-executions/{execution.id}/'
    assert client.get(base + 'logs/?after=invalid').status_code == 400
    initial = client.get(base + 'logs/?limit=1').data
    assert initial['next_after'] == 1
    assert client.get(base + 'logs/?after=1').data['logs'] == []
    ApiExecutionService().execute_existing_suite(execution.id)
    assert client.post(base + 'cancel/').status_code == 409


@pytest.mark.django_db
def test_worker_missing_execution_and_cancelled_execution(suite):
    assert execute_test_suite_task.apply(args=[999999], task_id='missing').get()['error'] == 'execution_not_found'
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    ExecutionStateMachine.transition(execution.id, 'CANCELLED')
    assert execute_test_suite_task.apply(args=[execution.id], task_id='cancelled').get()['cancelled'] is True


@pytest.mark.django_db
def test_worker_failure_records_safe_diagnostics(suite):
    user, test_suite = suite
    execution = ApiExecutionService().create_suite_execution(test_suite, user)
    with patch.object(ApiExecutionService, 'execute_existing_suite', side_effect=RuntimeError('password=do-not-persist')):
        with pytest.raises(RuntimeError, match='RuntimeError'):
            execute_test_suite_task.apply(args=[execution.id], task_id='failure').get()
    execution.refresh_from_db()
    assert execution.status == 'FAILED'
    assert 'do-not-persist' not in execution.error_message
    assert execution.logs.filter(event='TASK_ERROR').exists()
