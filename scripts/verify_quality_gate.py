"""Live acceptance: compatible PASS, breaking BLOCK despite green HTTP tests."""
import argparse
import json
from pathlib import Path
from quality_gate import GateClient


def verify(base_url, password):
    client = GateClient(base_url, 'testhub_demo', password)
    projects = client.call('GET', '/api-testing/projects/')
    projects = projects.get('results', []) if isinstance(projects, dict) else projects
    project = next(p for p in projects if p['name'] == 'QualityGate 演示')
    root = Path(__file__).resolve().parent.parent / 'fixtures/contracts'
    baseline = (root / 'baseline.json').read_text(encoding='utf-8')
    reports = []
    for candidate, expected in [('compatible', 'PASS'), ('breaking', 'BLOCK')]:
        report = client.run(project['id'], baseline, (root / f'{candidate}.json').read_text(encoding='utf-8'))
        assert report['decision'] == expected, report
        assert report['metrics']['pass_rate'] == 100, report
        assert report['metrics']['requests'] == 2, 'Login prerequisite must execute'
        assert report['impact']['selected_suites'] == 1 and report['impact']['total_suites'] == 2
        assert 'demo-session-token' not in json.dumps(report)
        reports.append({'scenario': candidate, **report})
    # Demonstrate an independent performance rule with a deterministic impossible budget.
    strict = client.run(project['id'], baseline, (root / 'compatible.json').read_text(encoding='utf-8'), {'max_p95_ms': .000001})
    assert strict['decision'] == 'BLOCK'
    assert not next(r for r in strict['rules'] if r['name'] == 'P95_LATENCY_MS')['passed']
    reports.append({'scenario': 'latency-budget', **strict})
    return reports


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--password', required=True)
    parser.add_argument('--output', default='quality-gate-verification.json')
    args = parser.parse_args()
    reports = verify(args.base_url, args.password)
    Path(args.output).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{'scenario': r['scenario'], 'decision': r['decision'], 'metrics': r['metrics']} for r in reports]))
