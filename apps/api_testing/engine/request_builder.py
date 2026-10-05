from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
import math

from .context import RunContext


@dataclass(frozen=True)
class RequestSpec:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    json_body: Any = None
    data_body: Any = None
    auth: tuple[str, str] | None = None
    timeout: float = 30.0

    def request_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            'method': self.method,
            'url': self.url,
            'headers': self.headers,
            'params': self.params,
            'timeout': self.timeout,
        }
        if self.auth:
            kwargs['auth'] = self.auth
        if self.json_body is not None:
            kwargs['json'] = self.json_body
        elif self.data_body is not None:
            kwargs['data'] = self.data_body
        return kwargs

    def snapshot(self) -> dict[str, Any]:
        return {
            'method': self.method,
            'url': self.url,
            'headers': dict(self.headers),
            'params': dict(self.params),
            'body': self.json_body if self.json_body is not None else self.data_body,
            'timeout': self.timeout,
        }


class RequestBuilder:
    BODY_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

    def build(self, definition: Mapping[str, Any], context: RunContext) -> RequestSpec:
        method = str(definition.get('method') or 'GET').upper()
        url = context.render_text(str(definition.get('url') or ''))
        if not url:
            raise ValueError('请求 URL 不能为空')

        headers = self._key_values(definition.get('headers'), context, stringify=True)
        params = self._key_values(definition.get('params'), context, stringify=False)
        auth = self._build_auth(definition.get('auth'), headers, context)
        json_body, data_body = self._build_body(method, definition.get('body'), context)
        timeout_value = definition.get('timeout', definition.get('timeout_seconds', 30))
        timeout = float(30 if timeout_value is None else timeout_value)
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError('请求超时时间必须为 0 到 120 秒之间的有限数值')

        return RequestSpec(method, url, headers, params, json_body, data_body, auth, timeout)

    @staticmethod
    def _key_values(value: Any, context: RunContext, *, stringify: bool) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if isinstance(value, list):
            entries = value
        elif isinstance(value, Mapping):
            entries = [{'key': key, 'value': item} for key, item in value.items()]
        else:
            entries = []
        for entry in entries:
            if not isinstance(entry, Mapping) or not entry.get('enabled', True) or not entry.get('key'):
                continue
            rendered = context.render(entry.get('value', ''))
            result[str(entry['key'])] = str(rendered) if stringify else rendered
        return result

    def _build_body(self, method: str, body: Any, context: RunContext) -> tuple[Any, Any]:
        if method not in self.BODY_METHODS or not isinstance(body, Mapping):
            return None, None
        body_type = str(body.get('type') or 'none').lower()
        content = body.get('data')
        if body_type == 'json':
            return context.render(content if content is not None else {}), None
        if body_type == 'raw':
            return None, context.render(content)
        if body_type in {'form-data', 'x-www-form-urlencoded', 'form'}:
            return None, self._key_values(content, context, stringify=False)
        return None, context.render(content) if content is not None else None

    @staticmethod
    def _build_auth(auth_value: Any, headers: dict[str, str], context: RunContext) -> tuple[str, str] | None:
        if not isinstance(auth_value, Mapping):
            return None
        auth_type = str(auth_value.get('type') or '').lower()
        if auth_type in {'bearer', 'bearer_token'}:
            token = context.render(auth_value.get('token', auth_value.get('value', '')))
            if token and not any(key.lower() == 'authorization' for key in headers):
                headers['Authorization'] = f'Bearer {token}'
            return None
        if auth_type in {'basic', 'basic_auth'}:
            username = str(context.render(auth_value.get('username', '')))
            password = str(context.render(auth_value.get('password', '')))
            return username, password
        return None
