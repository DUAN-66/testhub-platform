import math


def validate_performance_policy(value):
    defaults = {'max_p95_ms': 1000, 'max_error_rate': 0, 'min_rps': 1, 'min_requests': 20}
    if not isinstance(value, dict) or set(value) - {*defaults, 'max_queries'}:
        raise ValueError('Unknown performance policy field')
    result = {**defaults, **value}
    for key, number in result.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
            raise ValueError('Performance thresholds must be finite nonnegative numbers')
        if key in {'min_requests', 'max_queries'} and type(number) is not int:
            raise ValueError('Request/query limits must be integers')
    if not 1 <= result['min_requests'] <= 400 or result['max_p95_ms'] <= 0 or result['max_error_rate'] > 100:
        raise ValueError('Invalid performance thresholds')
    return result


def evaluate_performance(policy, evidence):
    rules = []

    def rule(name, passed, actual, expected):
        rules.append({'name': name, 'passed': bool(passed), 'actual': actual, 'expected': expected})

    valid = isinstance(evidence, dict) and evidence.get('status') == 'COMPLETED' and evidence.get('configuration_matches') is True
    summary = evidence.get('summary', {}) if isinstance(evidence, dict) else {}
    keys = ['requests', 'succeeded', 'failed', 'error_rate', 'successful_rps', 'p95_ms']
    valid &= isinstance(summary, dict)
    valid &= all(type(summary.get(key)) in {int, float} and math.isfinite(summary[key]) and summary[key] >= 0 for key in keys) if valid else False
    if valid:
        valid &= (summary['requests'] == summary['succeeded'] + summary['failed'] > 0
                  and all(type(summary[k]) is int for k in ['requests', 'succeeded', 'failed'])
                  and abs(summary['error_rate'] - summary['failed'] / summary['requests'] * 100) < 1e-6)
    rule('LOAD_EVIDENCE_COMPLETE', valid, valid, True)
    if valid:
        for name, key, threshold, greater in [
            ('LOAD_SAMPLE_COUNT', 'requests', 'min_requests', True),
            ('LOAD_P95_MS', 'p95_ms', 'max_p95_ms', False),
            ('LOAD_ERROR_RATE', 'error_rate', 'max_error_rate', False),
            ('LOAD_SUCCESSFUL_RPS', 'successful_rps', 'min_rps', True),
        ]:
            actual, expected = summary[key], policy[threshold]
            rule(name, actual >= expected if greater else actual <= expected, actual, expected)
        if 'max_queries' in policy:
            queries = summary.get('max_queries')
            query_valid = type(queries) is int and queries >= 0 and summary.get('query_samples') == summary['requests']
            rule('LOAD_SQL_QUERY_BUDGET', query_valid and queries <= policy['max_queries'], queries, policy['max_queries'])
    return rules
