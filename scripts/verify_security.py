"""Check production defaults and high-confidence credential leaks without printing secrets."""
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
PATTERNS = [
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{70,}'),
    re.compile(rb'AKIA[0-9A-Z]{16}'),
    re.compile(rb'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}'),
]


def scan_public_files():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    problems = []
    for name in filter(None, tracked):
        path = ROOT / name
        if not path.is_file():
            continue
        if path.name.startswith('.env') and path.name != '.env.example':
            problems.append(f'{name}: runtime configuration must not be tracked')
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in PATTERNS):
            problems.append(f'{name}: possible credential; inspect locally (value suppressed)')
    if problems:
        raise RuntimeError('\n'.join(problems))
    print('Public-file credential checks passed (high-confidence patterns only).')


def production_environment():
    env = os.environ.copy()
    env.update(DEBUG='False', SECRET_KEY=secrets.token_urlsafe(64), ALLOWED_HOSTS='testhub.example.invalid')
    for key in ('REGISTRATION_ENABLED', 'MCP_ENABLED', 'CORE_ONLY_MODE', 'API_TEST_ALLOWED_HOSTS', 'SECURE_SSL_REDIRECT',
                'APP_USE_HTTPS', 'CSRF_COOKIE_SECURE', 'SESSION_COOKIE_SECURE', 'TRUST_PROXY_SSL_HEADER'):
        env.pop(key, None)
    return env


def verify_production():
    env = production_environment()
    probe = '''
from backend import settings as s
assert not s.DEBUG and not s.REGISTRATION_ENABLED and not s.MCP_ENABLED and s.CORE_ONLY_MODE
assert s.API_TEST_ALLOWED_HOSTS == []
assert s.SECURE_SSL_REDIRECT and s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE
assert not s.TRUST_PROXY_SSL_HEADER
assert 'django.middleware.csrf.CsrfViewMiddleware' in s.MIDDLEWARE
assert 'django.middleware.clickjacking.XFrameOptionsMiddleware' in s.MIDDLEWARE
assert 'simpleui' not in s.INSTALLED_APPS
assert not any('DisableCSRF' in value for value in s.MIDDLEWARE)
print('Production default checks passed.')
'''
    subprocess.run([sys.executable, '-c', probe], cwd=ROOT, env=env, check=True)
    for overrides in ({'SECRET_KEY': ''}, {'SECRET_KEY': 'your-secret-key-here-change-in-production'}, {'ALLOWED_HOSTS': '*'}):
        result = subprocess.run([sys.executable, '-c', 'import backend.settings'], cwd=ROOT,
                                env={**env, **overrides}, capture_output=True)
        if result.returncode == 0 or b'ImproperlyConfigured' not in result.stderr:
            raise RuntimeError('Unsafe production configuration was not rejected')
    print('Missing/placeholder keys and wildcard hosts rejected.')
    subprocess.run([sys.executable, 'manage.py', 'check', '--deploy', '--tag=security', '--fail-level=ERROR', '--settings=backend.settings'],
                   cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    scan_public_files()
    verify_production()
