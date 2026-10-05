import copy
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.api_testing.models import ApiProject, ApiCollection, ApiRequest, TestSuite, TestSuiteRequest, TestExecution
from apps.contracts.models import ContractVersion
from apps.contracts.tests.test_contract import specification, schema
from apps.quality_gates.engine import evaluate, validate_policy
from apps.quality_gates.models import GateRun
from apps.users.models import User

DIFF = {'breaking_count': 0, 'review_count': 0}
IMPACT = {'suite_ids': [1], 'uncovered_operations': [], 'uncertain_suite_ids': []}


def evidence(status='COMPLETED', passed=True, latency=10):
    return [{'suite_id': 1, 'status': status, 'total_requests': 1,
             'results': [{'passed': passed, 'response_time': latency}]}]


@pytest.mark.parametrize('status', ['PENDING', 'QUEUED', 'RUNNING', 'CANCELLED'])
def test_nonterminal_or_cancelled_never_passes(status):
    assert evaluate(DIFF, IMPACT, evidence(status))['decision'] == 'BLOCK'


@pytest.mark.parametrize('latency', [-1, float('nan'), float('inf'), True, '10', None])
def test_invalid_latency_blocks(latency):
    assert evaluate(DIFF, IMPACT, evidence(latency=latency))['decision'] == 'BLOCK'


@pytest.mark.parametrize('policy', [[], {'unknown': 1}, {'min_pass_rate': 101}, {'max_p95_ms': 0}, {'min_pass_rate': True}])
def test_policy_validation(policy):
    with pytest.raises(ValueError):
        validate_policy(policy)


def test_missing_duplicate_and_incomplete_evidence_block():
    for executions in ([], evidence() * 2, [{**evidence()[0], 'results': []}], [{**evidence()[0], 'results': None}]):
        assert evaluate(DIFF, IMPACT, executions)['decision'] == 'BLOCK'


def test_no_semantic_changes_requires_no_execution():
    assert evaluate(DIFF, {**IMPACT, 'suite_ids': []}, [])['decision'] == 'PASS'


@pytest.mark.django_db
def test_demo_seeder_is_repeatable_and_preserves_accounts(settings):
    from django.core.management import call_command
    from django.core.management.base import CommandError
    settings.DEBUG = True
    call_command('seed_quality_demo', password='Demo-only!2026')
    call_command('seed_quality_demo', password='Demo-only!2026')
    assert ContractVersion.objects.count() == 3
    assert TestSuite.objects.count() == 2
    with pytest.raises(CommandError):
        call_command('seed_quality_demo', password='Different!')
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command('seed_quality_demo', password='Demo-only!2026')


def test_contract_and_coverage_are_independent_of_green_tests():
    assert evaluate({**DIFF, 'breaking_count': 1}, IMPACT, evidence())['decision'] == 'BLOCK'
    assert evaluate({**DIFF, 'review_count': 1}, IMPACT, evidence())['decision'] == 'BLOCK'
    assert evaluate(DIFF, {**IMPACT, 'uncovered_operations': ['GET /new']}, evidence())['decision'] == 'BLOCK'
    assert evaluate(DIFF, {**IMPACT, 'uncertain_suite_ids': [1]}, evidence())['decision'] == 'BLOCK'
    assert evaluate(DIFF, IMPACT, evidence())['decision'] == 'PASS'
    assert evaluate(DIFF, IMPACT, evidence(status='FAILED'))['decision'] == 'BLOCK'


def test_p95_nearest_rank_and_threshold_boundaries():
    run = evidence()[0]
    run['results'] = [{'passed': True, 'response_time': i} for i in range(1, 21)]
    run['total_requests'] = 20
    report = evaluate(DIFF, IMPACT, [run], {'max_p95_ms': 19})
    assert report['metrics']['p95_ms'] == 19 and report['decision'] == 'PASS'
    assert evaluate(DIFF, IMPACT, [run], {'max_p95_ms': 18})['decision'] == 'BLOCK'
    run['results'][0]['passed'] = False
    run['status'] = 'FAILED'
    assert evaluate(DIFF, IMPACT, [run], {'min_pass_rate': 95})['decision'] == 'PASS'
    assert evaluate(DIFF, IMPACT, [run])['decision'] == 'BLOCK'


@pytest.fixture
def assets(db):
    user = User.objects.create_user(username='quality-owner', password='test-only')
    project = ApiProject.objects.create(name='Gate', owner=user)
    collection = ApiCollection.objects.create(name='API', project=project)
    request = ApiRequest.objects.create(name='Profile', collection=collection, url='http://demo/profile', created_by=user)
    suite = TestSuite.objects.create(name='Critical', project=project, created_by=user)
    TestSuiteRequest.objects.create(test_suite=suite, request=request)
    before = specification()
    after = copy.deepcopy(before)
    schema(after)['properties']['nickname'] = {'type': 'string'}
    client = APIClient()
    client.force_authenticate(user)
    versions = [client.post('/api/v1/contracts/', {'project': project.id, 'name': name, 'document': doc}, format='json')
                for name, doc in [('baseline', before), ('candidate', after)]]
    assert all(v.status_code == 201 for v in versions)
    payload = {'baseline_id': versions[0].data['id'], 'candidate_id': versions[1].data['id']}
    return client, project, suite, request, payload


@pytest.mark.django_db
def test_import_deduplicated_immutable_and_project_scoped(assets):
    client, project, _, _, payload = assets
    result = client.post('/api/v1/contracts/', {'project': project.id, 'name': 'Again', 'document': specification()}, format='json')
    assert result.status_code == 200
    assert ContractVersion.objects.count() == 2
    assert client.patch(f"/api/v1/contracts/{payload['baseline_id']}/", {}, format='json').status_code == 405
    outsider = User.objects.create_user(username='outsider')
    client.force_authenticate(outsider)
    assert client.get('/api/v1/contracts/').data == []
    assert client.post('/api/v1/quality/plan/', payload, format='json').status_code == 404


@pytest.mark.django_db
def test_bound_run_idempotency_and_configuration_drift(assets):
    client, project, suite, request, payload = assets
    execution = TestExecution.objects.create(test_suite=suite, executed_by=project.owner, status='COMPLETED',
        total_requests=1, results=[{'passed': True, 'response_time': 10}])
    assert client.post('/api/v1/quality/execute/', payload, format='json').status_code == 400
    with patch('apps.quality_gates.views.dispatch_test_suite', return_value=execution) as dispatch:
        first = client.post('/api/v1/quality/execute/', payload, format='json', HTTP_IDEMPOTENCY_KEY='test-key')
        repeated = client.post('/api/v1/quality/execute/', payload, format='json', HTTP_IDEMPOTENCY_KEY='test-key')
        assert first.status_code == repeated.status_code == 202
        assert first.data['id'] == repeated.data['id'] and dispatch.call_count == 1
        conflict = client.post('/api/v1/quality/execute/', {**payload, 'policy': {'max_p95_ms': 20}}, format='json', HTTP_IDEMPOTENCY_KEY='test-key')
        assert conflict.status_code == 409
    evaluation = {'run_id': first.data['id']}
    assert client.post('/api/v1/quality/evaluate/', evaluation, format='json').data['decision'] == 'PASS'
    request.assertions = [{'type': 'status_code', 'expected': 500}]
    request.save()
    result = client.post('/api/v1/quality/evaluate/', evaluation, format='json')
    assert result.status_code == 201 and result.data['decision'] == 'BLOCK'
    assert not next(r for r in result.data['rules'] if r['name'] == 'CASE_CONFIGURATION_UNCHANGED')['passed']
    assert client.get('/api/v1/quality/invalid/run/').status_code == 400


@pytest.mark.django_db
def test_dispatch_failure_and_forged_evidence_block(assets):
    client, _, _, _, payload = assets
    with patch('apps.quality_gates.views.dispatch_test_suite', side_effect=RuntimeError('broker unavailable')):
        response = client.post('/api/v1/quality/execute/', payload, format='json', HTTP_IDEMPOTENCY_KEY='failed')
    assert response.data['state'] == 'ERROR'
    report = client.post('/api/v1/quality/evaluate/', {'run_id': response.data['id'], 'execution_ids': [999]}, format='json')
    assert report.data['decision'] == 'BLOCK'
    assert GateRun.objects.count() == 1
    outsider = User.objects.create_user(username='other')
    client.force_authenticate(outsider)
    assert client.get(f"/api/v1/quality/{response.data['id']}/run/").status_code == 404
    assert client.get('/api/v1/gate-reports/').data == []
