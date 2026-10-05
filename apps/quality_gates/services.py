from apps.api_testing.models import TestSuiteRequest
from apps.contracts.engine import compare, select_impact
from apps.contracts.engine import digest


def analyze(baseline, candidate):
    diff = compare(baseline.document, candidate.document)
    links = TestSuiteRequest.objects.filter(test_suite__project_id=baseline.project_id, enabled=True).select_related('request', 'test_suite__environment')
    cases = []
    for link in links:
        environment = link.test_suite.environment
        variables = environment.variables if environment else {}
        # Keep unrecognized environment formats unresolved; conservative selection will block the gate.
        variables = variables if isinstance(variables, dict) else {}
        cases.append({'suite_id': link.test_suite_id, 'method': link.request.method,
                      'url': link.request.url, 'variables': variables})
    return diff, select_impact(diff, cases)


def suite_fingerprints(project_id, suite_ids):
    links = TestSuiteRequest.objects.filter(test_suite__project_id=project_id, test_suite_id__in=suite_ids,
                                            enabled=True).select_related('request', 'test_suite__environment').order_by('test_suite_id', 'order', 'id')
    configurations = {}
    for link in links:
        request = link.request
        environment = link.test_suite.environment
        configurations.setdefault(str(link.test_suite_id), []).append({
            'request_id': request.id, 'order': link.order, 'method': request.method, 'url': request.url,
            'headers': request.headers, 'params': request.params, 'body': request.body, 'auth': request.auth,
            'assertions': [*(request.assertions or []), *(link.assertions or [])],
            'extractors': [*(request.extractors or []), *(link.extractors or [])],
            'environment_id': environment.id if environment else None,
            'variables': environment.variables if environment else {},
        })
    # No credential values are persisted in a plan, only a fingerprint.
    return {key: digest(value) for key, value in configurations.items()}
