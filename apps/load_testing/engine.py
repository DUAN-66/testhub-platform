"""Bounded closed-loop HTTP measurements. No scripts, bodies or credentials in results."""
import math
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from apps.api_testing.engine.context import RunContext
from apps.api_testing.engine.runner import ApiRunner


def validate_workload(value):
    defaults = {'users': 4, 'iterations': 10, 'timeout_seconds': 3}
    if not isinstance(value, dict) or set(value) - set(defaults):
        raise ValueError('Unknown workload field')
    workload = {**defaults, **value}
    for key, maximum in [('users', 8), ('iterations', 50), ('timeout_seconds', 5)]:
        number = workload[key]
        if type(number) is not int or not 1 <= number <= maximum:
            raise ValueError(f'{key} must be an integer from 1 to {maximum}')
    if (workload['users'] * workload['iterations'] * workload['timeout_seconds'] > 240
            or workload['iterations'] * workload['timeout_seconds'] > 45):
        raise ValueError('Worst-case request budget exceeds 240 seconds')
    return workload


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1] if values else None


def measure(definition, variables, workload, http_client):
    workload = validate_workload(workload)
    if definition.get('method') not in {'GET', 'HEAD'}:
        raise ValueError('Only saved GET/HEAD requests may be measured')
    definition = {**definition, 'timeout_seconds': workload['timeout_seconds']}
    barrier = Barrier(workload['users'])

    def worker(_):
        runner = ApiRunner(http_client=http_client)
        samples = []
        barrier.wait(timeout=10)
        for _ in range(workload['iterations']):
            started = time.perf_counter()
            result = runner.run(definition, RunContext.from_environment(variables),
                                assertions=definition.get('assertions', []))
            duration = (time.perf_counter() - started) * 1000
            code = getattr(result.response, 'status_code', 0)
            ok = result.passed and 200 <= code < 300
            query_count = getattr(result.response, 'headers', {}).get('X-Query-Count')
            try:
                query_count = int(query_count)
                if query_count < 0:
                    query_count = None
            except (ValueError, TypeError):
                query_count = None
            samples.append((duration, ok, query_count))
        return samples

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workload['users']) as pool:
        samples = [sample for batch in pool.map(worker, range(workload['users'])) for sample in batch]
    elapsed = time.perf_counter() - started
    latencies = [sample[0] for sample in samples]
    queries = [sample[2] for sample in samples if sample[2] is not None]
    succeeded = sum(sample[1] for sample in samples)
    return {'requests': len(samples), 'succeeded': succeeded, 'failed': len(samples) - succeeded,
            'error_rate': (len(samples) - succeeded) / len(samples) * 100,
            'elapsed_seconds': elapsed, 'successful_rps': succeeded / elapsed,
            'p50_ms': percentile(latencies, .50), 'p95_ms': percentile(latencies, .95),
            'p99_ms': percentile(latencies, .99), 'query_samples': len(queries),
            'max_queries': max(queries) if queries else None,
            'workload': workload, 'percentile_method': 'nearest-rank',
            'model': 'bounded-closed-loop/v1'}
