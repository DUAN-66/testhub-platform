import copy
import pytest

from apps.contracts.engine import ContractError, compare, normalize, select_impact


def specification():
    return {'openapi': '3.0.3', 'info': {'title': 'Demo', 'version': '1'}, 'paths': {
        '/profile': {'get': {'responses': {'200': {'description': 'OK', 'content': {
            'application/json': {'schema': {'type': 'object', 'required': ['id'],
                                         'properties': {'id': {'type': 'integer'}}}}}}}}}}}


def schema(document):
    return document['paths']['/profile']['get']['responses']['200']['content']['application/json']['schema']


@pytest.mark.parametrize('mutation,severity', [
    (lambda d: schema(d)['properties']['id'].update(type='string'), 'BREAKING'),
    (lambda d: schema(d).pop('required'), 'BREAKING'),
    (lambda d: schema(d)['properties'].pop('id'), 'BREAKING'),
    (lambda d: schema(d)['properties'].update(nickname={'type': 'string'}), 'COMPATIBLE'),
    (lambda d: schema(d)['properties']['id'].update(minimum=0), 'REVIEW'),
    (lambda d: d['paths']['/profile']['get'].update(security=[{'bearer': []}]) or d.update(
        components={'securitySchemes': {'bearer': {'type': 'http', 'scheme': 'bearer'}}}), 'REVIEW'),
    (lambda d: d['paths'].pop('/profile'), 'BREAKING'),
])
def test_semantic_mutations(mutation, severity):
    before = specification()
    after = copy.deepcopy(before)
    mutation(after)
    diff = compare(before, after)
    assert diff['changed_operations'] == ['GET /profile']
    assert severity in {c['severity'] for c in diff['changes']}


@pytest.mark.parametrize('direction,old,new,breaking', [
    ('request', ['a', 'b'], ['a'], True), ('request', ['a'], ['a', 'b'], False),
    ('response', ['a'], ['a', 'b'], True), ('response', ['a', 'b'], ['a'], False),
])
def test_enum_variance(direction, old, new, breaking):
    before = specification()
    if direction == 'request':
        before['paths']['/profile']['get']['parameters'] = [
            {'in': 'query', 'name': 'kind', 'schema': {'type': 'string', 'enum': old}}]
    else:
        schema(before)['properties']['id'] = {'type': 'string', 'enum': old}
    after = copy.deepcopy(before)
    target = (after['paths']['/profile']['get']['parameters'][0]['schema'] if direction == 'request'
              else schema(after)['properties']['id'])
    target['enum'] = new
    assert bool(compare(before, after)['breaking_count']) is breaking


def test_metadata_is_not_a_semantic_change():
    before = specification()
    after = copy.deepcopy(before)
    schema(after)['description'] = 'New documentation'
    assert compare(before, after)['changes'] == []


@pytest.mark.parametrize('document', [
    {'openapi': '3.1.0'}, '{invalid', 'a: &a [*a]',
    {'openapi': '3.0.3', 'paths': {}, 'info': {'title': 'x', 'version': '1'}, '$ref': 'https://example.com/schema'},
    {'openapi': '3.0.3', 'paths': {}, 'info': {'title': 'x', 'version': '1'}, 'x': float('nan')},
])
def test_unsafe_or_unsupported_imports_are_rejected(document):
    with pytest.raises(ContractError):
        normalize(document)


def test_local_reference_expansion_and_cycle_rejection():
    document = specification()
    original = copy.deepcopy(schema(document))
    document['components'] = {'schemas': {'Profile': original}}
    document['paths']['/profile']['get']['responses']['200']['content']['application/json']['schema'] = {
        '$ref': '#/components/schemas/Profile'}
    assert normalize(document)[1]['GET /profile']['responses']['200']['content']['application/json']['schema'] == original
    document['components']['schemas']['Profile'] = {'$ref': '#/components/schemas/Profile'}
    with pytest.raises(ContractError):
        normalize(document)


def test_selection_keeps_prerequisites_and_resolves_path_parameters():
    diff = {'changed_operations': ['GET /users/{id}']}
    cases = [
        {'suite_id': 1, 'method': 'POST', 'url': 'http://demo/login'},
        {'suite_id': 1, 'method': 'GET', 'url': '{{base}}/users/7?verbose=1', 'variables': {'base': 'http://demo'}},
        {'suite_id': 2, 'method': 'GET', 'url': 'http://demo/health'},
        {'suite_id': 3, 'method': 'GET', 'url': '{{unknown}}/users/7'},
    ]
    result = select_impact(diff, cases)
    assert result['suite_ids'] == [1, 3]
    assert result['uncertain_suite_ids'] == [3]
    assert result['uncovered_operations'] == []
    assert result['total_suites'] == 3


def test_uncovered_change_is_reported():
    assert select_impact({'changed_operations': ['DELETE /missing']}, [])['uncovered_operations'] == ['DELETE /missing']


@pytest.mark.parametrize('mutation,severity', [
    (lambda d: d['paths'].update({'/new': {'get': {'responses': {'200': {'description': 'OK'}}}}}), 'COMPATIBLE'),
    (lambda d: d['paths']['/profile']['get'].update(parameters=[{'name': 'x', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}]), 'BREAKING'),
    (lambda d: d['paths']['/profile']['get'].update(requestBody={'required': True, 'content': {'application/json': {'schema': {'type': 'string'}}}}), 'BREAKING'),
    (lambda d: d['paths']['/profile']['get']['responses'].update({'400': {'description': 'Bad'}}), 'REVIEW'),
    (lambda d: d['paths']['/profile']['get']['responses']['200'].update(headers={'X-Id': {'schema': {'type': 'string'}}}), 'REVIEW'),
    (lambda d: d['paths']['/profile']['get']['responses']['200']['content'].update({'text/plain': {'schema': {'type': 'string'}}}), 'REVIEW'),
])
def test_operation_parameter_and_media_mutations(mutation, severity):
    before = specification()
    after = copy.deepcopy(before)
    mutation(after)
    assert severity in {c['severity'] for c in compare(before, after)['changes']}


def test_parameter_removal_required_and_encoding_semantics():
    before = specification()
    before['paths']['/profile']['get']['parameters'] = [
        {'name': 'x', 'in': 'query', 'schema': {'type': 'string'}}]
    after = copy.deepcopy(before)
    after['paths']['/profile']['get']['parameters'][0].update(required=True, style='form')
    diff = compare(before, after)
    assert diff['breaking_count'] == 1 and diff['review_count'] == 1
    after['paths']['/profile']['get']['parameters'] = []
    assert compare(before, after)['breaking_count'] == 1


def test_recursive_array_schema_and_required_request_property():
    before = specification()
    before['paths']['/profile']['get']['requestBody'] = {'content': {'application/json': {'schema': {
        'type': 'array', 'items': {'type': 'object', 'properties': {'id': {'type': 'integer'}}}}}}}
    after = copy.deepcopy(before)
    item = after['paths']['/profile']['get']['requestBody']['content']['application/json']['schema']['items']
    item['properties']['token'] = {'type': 'string'}
    item['required'] = ['token']
    assert compare(before, after)['breaking_count'] == 2


@pytest.mark.parametrize('kind', ['size', 'depth', 'missing-ref', 'invalid-schema', 'siblings'])
def test_resource_limits_and_invalid_references(kind):
    document = specification()
    if kind == 'size':
        document['x-large'] = 'a' * 1_000_001
    elif kind == 'depth':
        value = document
        for _ in range(60):
            value['x-deep'] = {}
            value = value['x-deep']
    elif kind == 'missing-ref':
        schema(document)['properties']['id'] = {'$ref': '#/missing'}
    elif kind == 'siblings':
        schema(document)['properties']['id'] = {'$ref': '#/missing', 'type': 'integer'}
    else:
        document['info'].pop('title')
    with pytest.raises(ContractError):
        normalize(document)
