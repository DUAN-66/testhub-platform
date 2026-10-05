"""Conservative consumer compatibility analysis for a bounded OpenAPI 3.0 subset.

Unknown semantic changes require review; they never silently pass a release gate.
No remote references or network imports are permitted.
"""
import copy
import hashlib
import json
import re
from urllib.parse import urlsplit

import yaml
from openapi_spec_validator import validate

METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}
METADATA = {'description', 'summary', 'example', 'examples', 'externalDocs', 'operationId', 'tags'}


class ContractError(ValueError):
    pass


def normalize(document):
    if isinstance(document, str):
        if len(document.encode()) > 1_000_000:
            raise ContractError('Contract exceeds 1 MB')
        try:
            if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(document)):
                raise ContractError('YAML aliases are not supported; use local JSON references')
            document = yaml.safe_load(document)
        except (yaml.YAMLError, RecursionError) as exc:
            raise ContractError('Invalid JSON/YAML document') from exc
    try:
        encoded = json.dumps(document, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContractError('Contract must contain finite JSON values without cycles') from exc
    if len(encoded.encode()) > 1_000_000:
        raise ContractError('Contract exceeds 1 MB')
    if not isinstance(document, dict) or not str(document.get('openapi', '')).startswith('3.0.'):
        raise ContractError('This compatibility profile supports OpenAPI 3.0 only')
    budget = [30_000]

    def expand(value, references=(), depth=0):
        budget[0] -= 1
        if budget[0] < 0 or depth > 50:
            raise ContractError('Contract expansion exceeds complexity limit')
        if isinstance(value, list):
            return [expand(item, references, depth + 1) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            ref = value['$ref']
            if not isinstance(ref, str) or not ref.startswith('#/'):
                raise ContractError('Only local JSON pointer references are allowed')
            if ref in references or len(value) != 1:
                raise ContractError('Recursive references and reference siblings require manual review')
            target = document
            try:
                for segment in ref[2:].split('/'):
                    key = segment.replace('~1', '/').replace('~0', '~')
                    target = target[int(key)] if isinstance(target, list) else target[key]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ContractError('Unresolved local reference') from exc
            return expand(target, (*references, ref), depth + 1)
        return {key: expand(item, references, depth + 1) for key, item in value.items()}

    expanded = expand(document)
    try:
        validate(expanded)
    except Exception as exc:
        # Validator exceptions may include embedded example credentials.
        raise ContractError('Document does not satisfy the OpenAPI 3.0 schema') from exc
    operations = {}
    for path, path_item in expanded['paths'].items():
        inherited = path_item.get('parameters', [])
        for method in sorted(METHODS & path_item.keys()):
            operation = copy.deepcopy(path_item[method])
            parameters = {(p['in'], p['name']): p for p in inherited}
            parameters.update({(p['in'], p['name']): p for p in operation.get('parameters', [])})
            operation['parameters'] = sorted(parameters.values(), key=lambda p: (p['in'], p['name']))
            operation['security'] = operation.get('security', expanded.get('security', []))
            operation['servers'] = operation.get('servers', path_item.get('servers', expanded.get('servers', [])))
            # Security scheme changes are semantic even if operation requirements are unchanged.
            operation['securitySchemes'] = expanded.get('components', {}).get('securitySchemes', {})
            operations[f'{method.upper()} {path}'] = operation
    return document, operations


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def compare(baseline, candidate):
    _, old = normalize(baseline)
    _, new = normalize(candidate)
    changes = []

    def add(operation, location, severity, rule):
        changes.append({'operation': operation, 'location': location, 'severity': severity, 'rule': rule})

    def schema(operation, before, after, direction, location):
        if before == after:
            return
        if not isinstance(before, dict) or not isinstance(after, dict):
            add(operation, location, 'REVIEW', 'SCHEMA_SHAPE_CHANGED')
            return
        handled = METADATA | {'properties', 'required', 'items', 'type', 'enum'}
        if before.get('type') != after.get('type'):
            add(operation, location, 'BREAKING', 'SCHEMA_TYPE_CHANGED')
        old_enum, new_enum = before.get('enum'), after.get('enum')
        if old_enum != new_enum:
            old_values = set(map(json.dumps, old_enum)) if old_enum is not None else None
            new_values = set(map(json.dumps, new_enum)) if new_enum is not None else None
            narrowed = new_values is not None and (old_values is None or not old_values <= new_values)
            widened = old_values is not None and (new_values is None or not new_values <= old_values)
            breaking = narrowed if direction == 'request' else widened
            add(operation, location + '/enum', 'BREAKING' if breaking else 'COMPATIBLE', 'ENUM_VALUES_CHANGED')
        old_required, new_required = set(before.get('required', [])), set(after.get('required', []))
        if old_required != new_required:
            breaking = bool(new_required - old_required) if direction == 'request' else bool(old_required - new_required)
            add(operation, location + '/required', 'BREAKING' if breaking else 'COMPATIBLE', 'REQUIRED_PROPERTIES_CHANGED')
        old_properties, new_properties = before.get('properties', {}), after.get('properties', {})
        for key in sorted(old_properties.keys() | new_properties.keys()):
            child = location + '/properties/' + key
            if key not in new_properties:
                # Removed request properties might now be rejected; don't assume extra keys are accepted.
                add(operation, child, 'BREAKING', 'PROPERTY_REMOVED')
            elif key not in old_properties:
                severity = 'BREAKING' if direction == 'request' and key in new_required else 'COMPATIBLE'
                add(operation, child, severity, 'PROPERTY_ADDED')
            else:
                schema(operation, old_properties[key], new_properties[key], direction, child)
        if before.get('items') != after.get('items'):
            schema(operation, before.get('items', {}), after.get('items', {}), direction, location + '/items')
        for key in sorted((before.keys() | after.keys()) - handled):
            if before.get(key) != after.get(key):
                # Bounds, composition, nullable, discriminator, formats, etc. cannot be proved compatible here.
                add(operation, location + '/' + key, 'REVIEW', 'UNCLASSIFIED_SCHEMA_CHANGE')

    def content(operation, before, after, direction, location):
        for media in sorted(before.keys() | after.keys()):
            if media not in before or media not in after:
                add(operation, location + '/' + media, 'REVIEW', 'MEDIA_TYPE_CHANGED')
            else:
                schema(operation, before[media].get('schema', {}), after[media].get('schema', {}), direction, location + '/' + media)
                for key in (before[media].keys() | after[media].keys()) - (METADATA | {'schema'}):
                    if before[media].get(key) != after[media].get(key):
                        add(operation, location + '/' + media + '/' + key, 'REVIEW', 'MEDIA_SEMANTICS_CHANGED')

    for operation in sorted(old.keys() | new.keys()):
        if operation not in new:
            add(operation, '/', 'BREAKING', 'OPERATION_REMOVED')
            continue
        if operation not in old:
            add(operation, '/', 'COMPATIBLE', 'OPERATION_ADDED')
            continue
        before, after = old[operation], new[operation]
        old_params = {(p['in'], p['name']): p for p in before['parameters']}
        new_params = {(p['in'], p['name']): p for p in after['parameters']}
        for key in sorted(old_params.keys() | new_params.keys()):
            location = '/parameters/' + '/'.join(key)
            if key not in old_params:
                add(operation, location, 'BREAKING' if new_params[key].get('required') else 'COMPATIBLE', 'PARAMETER_ADDED')
            elif key not in new_params:
                add(operation, location, 'BREAKING', 'PARAMETER_REMOVED')
            else:
                a, b = old_params[key], new_params[key]
                if bool(a.get('required')) != bool(b.get('required')):
                    add(operation, location, 'BREAKING' if b.get('required') else 'COMPATIBLE', 'PARAMETER_REQUIRED_CHANGED')
                schema(operation, a.get('schema', {}), b.get('schema', {}), 'request', location)
                for field in (a.keys() | b.keys()) - (METADATA | {'schema', 'required', 'name', 'in'}):
                    if a.get(field) != b.get(field):
                        add(operation, location + '/' + field, 'REVIEW', 'PARAMETER_SEMANTICS_CHANGED')
        a, b = before.get('requestBody', {}), after.get('requestBody', {})
        if bool(a.get('required')) != bool(b.get('required')):
            add(operation, '/requestBody', 'BREAKING' if b.get('required') else 'COMPATIBLE', 'REQUEST_BODY_REQUIRED_CHANGED')
        content(operation, a.get('content', {}), b.get('content', {}), 'request', '/requestBody')
        for status in sorted(before['responses'].keys() | after['responses'].keys()):
            location = '/responses/' + status
            if status not in after['responses']:
                add(operation, location, 'BREAKING', 'RESPONSE_REMOVED')
            elif status not in before['responses']:
                add(operation, location, 'REVIEW', 'RESPONSE_ADDED')
            else:
                a, b = before['responses'][status], after['responses'][status]
                content(operation, a.get('content', {}), b.get('content', {}), 'response', location)
                for field in (a.keys() | b.keys()) - (METADATA | {'content'}):
                    if a.get(field) != b.get(field):
                        add(operation, location + '/' + field, 'REVIEW', 'RESPONSE_SEMANTICS_CHANGED')
        for field in (before.keys() | after.keys()) - (METADATA | {'parameters', 'responses', 'requestBody'}):
            if before.get(field) != after.get(field):
                add(operation, '/' + field, 'REVIEW', 'OPERATION_SEMANTICS_CHANGED')
    return {'changes': changes, 'changed_operations': sorted({c['operation'] for c in changes}),
            'breaking_count': sum(c['severity'] == 'BREAKING' for c in changes),
            'review_count': sum(c['severity'] == 'REVIEW' for c in changes)}


def select_impact(diff, cases):
    """Select complete suites so login/extraction prerequisites are preserved."""
    impacted, uncertain, covered = set(), set(), set()
    total_suites = {case['suite_id'] for case in cases}
    for case in cases:
        url = case['url']
        variables = case.get('variables', {})
        url = re.sub(r'\{\{\s*([\w]+)\s*\}\}', lambda m: str(variables.get(m[1], m[0])), url)
        if '{{' in url:
            uncertain.add(case['suite_id'])
            continue
        request_path = urlsplit(url).path
        for operation in diff['changed_operations']:
            method, path = operation.split(' ', 1)
            pattern = '^' + re.sub(r'\\\{[^}]+\\\}', '[^/]+', re.escape(path)) + '$'
            if case['method'].upper() == method and re.fullmatch(pattern, request_path):
                impacted.add(case['suite_id'])
                covered.add(operation)
    selected = (impacted | uncertain) if diff['changed_operations'] else set()
    return {'suite_ids': sorted(selected), 'total_suites': len(total_suites),
            'selected_suites': len(selected), 'uncertain_suite_ids': sorted(uncertain),
            'uncovered_operations': sorted(set(diff['changed_operations']) - covered),
            'strategy': 'CONSERVATIVE_WITH_PREREQUISITES'}
