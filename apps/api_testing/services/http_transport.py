"""Outbound boundary for persisted API executions.

Only operator-configured hosts may receive requests. Redirects and environment
proxies are disabled; TLS verification remains enabled. Network egress isolation
is still required for production because other platform modules use own clients.
"""
from urllib.parse import urlsplit
import requests
from django.conf import settings


class RestrictedHttpClient:
    def __init__(self, *, allowed_hosts=None):
        self.allowed_hosts = settings.API_TEST_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts

    def request(self, **kwargs):
        try:
            target = urlsplit(kwargs['url'])
            host = (target.hostname or '').lower().rstrip('.')
            target.port  # Validate malformed/out-of-range ports before connecting.
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid target URL') from exc
        allowed = {item.lower().rstrip('.') for item in self.allowed_hosts}
        if target.scheme not in {'http', 'https'} or not host or target.username is not None or target.password is not None:
            raise ValueError('Only HTTP(S) URLs without embedded credentials are permitted')
        if host not in allowed or '*' in allowed:
            raise ValueError('Target host is not in API_TEST_ALLOWED_HOSTS')
        if any(key.lower() in {'host', 'proxy-authorization'} for key in kwargs.get('headers', {})):
            raise ValueError('Host and proxy authorization headers cannot be overridden')
        kwargs.update(allow_redirects=False, verify=True, stream=True)
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(**kwargs)
            try:
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > settings.API_TEST_MAX_RESPONSE_BYTES:
                        raise ValueError('Response exceeds API_TEST_MAX_RESPONSE_BYTES')
                    chunks.append(chunk)
                response._content = b''.join(chunks)
                response._content_consumed = True
                return response
            finally:
                response.close()
