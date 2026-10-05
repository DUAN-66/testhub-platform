"""Pure, deterministic release decisions with explicit evidence for every rule."""
import math

DEFAULT_POLICY = {'min_pass_rate': 100.0, 'max_p95_ms': 1000.0}


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) - set(DEFAULT_POLICY):
        raise ValueError('Unknown quality gate policy field')
    policy = {**DEFAULT_POLICY, **policy}
    for key, value in policy.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Policy values must be finite numbers')
    if not 0 <= policy['min_pass_rate'] <= 100 or policy['max_p95_ms'] <= 0:
        raise ValueError('Invalid policy thresholds')
    return policy


def evaluate(diff, impact, executions, policy=None):
    policy = validate_policy({} if policy is None else policy)
    rules = []

    def rule(name, passed, actual, expected):
        rules.append({'name': name, 'passed': bool(passed), 'actual': actual, 'expected': expected})

    rule('CONTRACT_COMPATIBILITY', diff['breaking_count'] == 0, diff['breaking_count'], 0)
    rule('MANUAL_REVIEW_REQUIRED', diff['review_count'] == 0, diff['review_count'], 0)
    rule('CHANGE_COVERAGE', not impact['uncovered_operations'], impact['uncovered_operations'], [])
    rule('CASE_MAPPING_RESOLVED', not impact['uncertain_suite_ids'], impact['uncertain_suite_ids'], [])
    expected = set(impact['suite_ids'])
    actual = {item['suite_id'] for item in executions}
    rule('SUITE_EVIDENCE', actual == expected and len(actual) == len(executions), sorted(actual), sorted(expected))
    samples, passed, total, complete = [], 0, 0, True
    for execution in executions:
        results = execution['results']
        complete &= execution['status'] in {'COMPLETED', 'FAILED'}
        complete &= isinstance(results, list) and len(results) == execution['total_requests'] > 0
        if not isinstance(results, list):
            continue
        if results:
            all_passed = all(isinstance(r, dict) and r.get('passed') is True for r in results)
            complete &= (execution['status'] == 'COMPLETED' and all_passed) or (execution['status'] == 'FAILED' and not all_passed)
        for result in results:
            valid = isinstance(result, dict) and type(result.get('passed')) is bool
            latency = result.get('response_time') if isinstance(result, dict) else None
            valid &= isinstance(latency, (int, float)) and not isinstance(latency, bool)
            valid &= math.isfinite(latency) and latency >= 0 if valid else False
            complete &= valid
            if valid:
                total += 1
                passed += result['passed']
                samples.append(latency)
    if expected:
        rule('EXECUTION_COMPLETE', complete and bool(total), bool(complete and total), True)
        pass_rate = passed / total * 100 if total else 0
        p95 = sorted(samples)[math.ceil(len(samples) * .95) - 1] if samples else None
        rule('PASS_RATE', pass_rate >= policy['min_pass_rate'], round(pass_rate, 3), policy['min_pass_rate'])
        rule('P95_LATENCY_MS', p95 is not None and p95 <= policy['max_p95_ms'], p95, policy['max_p95_ms'])
    else:
        pass_rate, p95 = None, None
    return {'decision': 'PASS' if all(item['passed'] for item in rules) else 'BLOCK', 'rules': rules,
            'metrics': {'requests': total, 'passed': passed, 'pass_rate': pass_rate, 'p95_ms': p95},
            'policy': policy, 'percentile_method': 'nearest-rank', 'evidence_schema': 'qualitygate/v1'}
