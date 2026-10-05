from types import SimpleNamespace
from unittest.mock import patch
import pytest
from apps.load_testing.engine import measure, validate_workload, percentile
from apps.load_testing.policy import validate_performance_policy, evaluate_performance
from apps.quality_gates.engine import evaluate, validate_policy
from apps.quality_gates.tests.test_gate import assets, DIFF, IMPACT, evidence
from apps.load_testing.models import PerformanceRun
from apps.load_testing.services import fingerprint


@pytest.mark.parametrize('value', [[], {'unknown': 1}, {'users': True}, {'users': 0}, {'users': 9},
                                 {'iterations': 51}, {'timeout_seconds': 6}, {'users': 8, 'iterations': 50}])
def test_unbounded_workloads_rejected(value):
    with pytest.raises(ValueError):
        validate_workload(value)


@pytest.mark.parametrize('value', [[], {'unknown': 1}, {'min_rps': True}, {'max_p95_ms': float('nan')},
                                 {'min_requests': 1.5}, {'min_requests': 0}, {'min_requests': 401},
                                 {'max_p95_ms': 0}, {'max_error_rate': 101}, {'min_rps': -1}])
def test_invalid_performance_policy_rejected(value):
    with pytest.raises(ValueError):
        validate_policy({'performance': value})


class Client:
    def __init__(self, status=200, queries='1', fail=False):
        self.status, self.queries, self.fail = status, queries, fail

    def request(self, **kwargs):
        assert kwargs['timeout'] == 1
        if self.fail:
            raise RuntimeError('secret-token-must-not-appear')
        return SimpleNamespace(status_code=self.status, headers={'X-Query-Count': self.queries})


@pytest.mark.parametrize('status,queries,fail', [(200, '1', False), (500, '-1', False), (401, 'bad', False), (200, None, True)])
def test_real_attempts_errors_and_missing_sql_evidence(status, queries, fail):
    result = measure({'method': 'GET', 'url': 'http://fixture'}, {},
                     {'users': 2, 'iterations': 3, 'timeout_seconds': 1}, Client(status, queries, fail))
    assert result['requests'] == 6
    assert result['succeeded'] == (6 if status == 200 and not fail else 0)
    assert result['p95_ms'] >= 0 and result['successful_rps'] >= 0
    assert result['query_samples'] == (6 if queries == '1' and not fail else 0)
    assert 'secret-token' not in str(result)


def test_read_only_methods_and_percentile():
    with pytest.raises(ValueError):
        measure({'method': 'POST'}, {}, {}, Client())
    assert percentile(list(range(1, 21)), .95) == 19
    assert percentile([], .95) is None


def test_performance_budget_is_independent_of_green_functional_tests():
    summary = {'requests': 20, 'succeeded': 20, 'failed': 0, 'error_rate': 0,
               'successful_rps': 100, 'p95_ms': 10, 'query_samples': 20, 'max_queries': 1}
    proof = {'status': 'COMPLETED', 'configuration_matches': True, 'summary': summary}
    policy = {'performance': {'max_queries': 1}}
    assert evaluate(DIFF, IMPACT, evidence(), policy, proof)['decision'] == 'PASS'
    for broken in [None, {}, {**proof, 'status': 'RUNNING'}, {**proof, 'configuration_matches': False},
                   {**proof, 'summary': []}, {**proof, 'summary': {**summary, 'p95_ms': float('inf')}},
                   {**proof, 'summary': {**summary, 'succeeded': 19}}]:
        assert evaluate(DIFF, IMPACT, evidence(), policy, broken)['decision'] == 'BLOCK'
    for changes in [{'max_queries': 0}, {'max_p95_ms': 1}, {'min_rps': 101}, {'min_requests': 21}]:
        assert evaluate(DIFF, IMPACT, evidence(), {'performance': changes}, proof)['decision'] == 'BLOCK'
    for changes in [{'max_queries': None}, {'query_samples': 19}, {'failed': 1, 'succeeded': 19, 'error_rate': 5}]:
        assert evaluate(DIFF, IMPACT, evidence(), policy, {**proof, 'summary': {**summary, **changes}})['decision'] == 'BLOCK'
    assert evaluate_performance(validate_performance_policy({}), proof)[0]['passed']


@pytest.mark.django_db
def test_dispatch_idempotency_access_and_server_bound_evidence(assets):
    client, project, suite, target, payload = assets
    from apps.api_testing.models import TestExecution
    execution = TestExecution.objects.create(test_suite=suite, executed_by=project.owner, status='COMPLETED',
                                             total_requests=1, results=[{'passed': True, 'response_time': 1}])
    payload['policy'] = {'performance': {}}
    with patch('apps.quality_gates.views.dispatch_test_suite', return_value=execution):
        gate = client.post('/api/v1/quality/execute/', payload, format='json', HTTP_IDEMPOTENCY_KEY='gate').data
    assert client.post('/api/v1/quality/evaluate/', {'run_id': gate['id'], 'summary': {'p95_ms': 0}}, format='json').data['decision'] == 'BLOCK'
    data = {'request_id': target.pk, 'gate_id': gate['id'], 'workload': {'users': 1, 'iterations': 20, 'timeout_seconds': 2}}
    with patch('apps.load_testing.views.execute_performance.apply_async') as dispatch:
        first = client.post('/api/v1/performance/', data, format='json', HTTP_IDEMPOTENCY_KEY='load')
        replay = client.post('/api/v1/performance/', data, format='json', HTTP_IDEMPOTENCY_KEY='load')
        assert first.status_code == replay.status_code == 202
        assert first.data['id'] == replay.data['id'] and dispatch.call_count == 1
        assert client.post('/api/v1/performance/', {**data, 'workload': {'users': 2}}, format='json', HTTP_IDEMPOTENCY_KEY='load').status_code == 409
        assert client.post('/api/v1/performance/', data, format='json', HTTP_IDEMPOTENCY_KEY='other').status_code == 409
    run = PerformanceRun.objects.get(pk=first.data['id'])
    run.status = 'COMPLETED'
    run.summary = {'requests': 20, 'succeeded': 20, 'failed': 0, 'error_rate': 0, 'p95_ms': 1, 'successful_rps': 100}
    run.save()
    assert client.post('/api/v1/quality/evaluate/', {'run_id': gate['id']}, format='json').data['decision'] == 'PASS'
    target.params = {'changed': True}
    target.save()
    assert client.post('/api/v1/quality/evaluate/', {'run_id': gate['id']}, format='json').data['decision'] == 'BLOCK'
    assert client.patch(f'/api/v1/performance/{run.pk}/', {'summary': {}}, format='json').status_code == 405
    from apps.users.models import User
    client.force_authenticate(User.objects.create_user(username='load-outsider'))
    assert client.get(f'/api/v1/performance/{run.pk}/').status_code == 404
    assert client.post('/api/v1/performance/', data, format='json', HTTP_IDEMPOTENCY_KEY='outside').status_code == 404


@pytest.mark.django_db
def test_worker_claims_once_and_rechecks_configuration(assets, settings):
    from apps.load_testing.tasks import execute_performance
    client, project, _, target, _ = assets
    with patch('apps.load_testing.views.execute_performance.apply_async'):
        created = client.post('/api/v1/performance/', {'request_id': target.pk}, format='json', HTTP_IDEMPOTENCY_KEY='worker')
    run = PerformanceRun.objects.get(pk=created.data['id'])
    with patch('apps.load_testing.tasks.measure', return_value={'requests': 40}) as measure_mock:
        execute_performance.apply(args=[str(run.pk)], task_id='wrong')
        assert measure_mock.call_count == 0
        execute_performance.apply(args=[str(run.pk)], task_id=run.task_id)
        execute_performance.apply(args=[str(run.pk)], task_id=run.task_id)
        assert measure_mock.call_count == 1
    run.refresh_from_db()
    assert run.status == 'COMPLETED' and run.finished_at
    run.status = 'QUEUED'
    run.configuration_digest = 'changed'
    run.save()
    execute_performance.apply(args=[str(run.pk)], task_id=run.task_id)
    run.refresh_from_db()
    assert run.status == 'FAILED' and run.error_code == 'MEASUREMENT_FAILED'


@pytest.mark.django_db
def test_broker_failure_is_persisted(assets):
    client, _, _, target, _ = assets
    with patch('apps.load_testing.views.execute_performance.apply_async', side_effect=RuntimeError('secret')):
        result = client.post('/api/v1/performance/', {'request_id': target.pk}, format='json', HTTP_IDEMPOTENCY_KEY='broker')
    assert result.data['status'] == 'FAILED' and result.data['error_code'] == 'DISPATCH_FAILED'
    assert 'secret' not in str(result.data)
