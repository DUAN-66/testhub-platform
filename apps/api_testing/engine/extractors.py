from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from jsonpath_ng import parse as parse_json_path

from .context import RunContext


@dataclass(frozen=True)
class ExtractionResult:
    name: str
    source: str
    expression: str
    success: bool
    value: Any = None
    error: str | None = None
    required: bool = False
    secret: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'source': self.source,
            'expression': self.expression,
            'success': self.success,
            'value': '******' if self.secret and self.success else self.value,
            'error': self.error,
            'required': self.required,
        }


class ExtractorEngine:
    """Extract response values and write successful results into RunContext."""

    def extract(
        self,
        response: Any,
        rules: Iterable[Mapping[str, Any]] | None,
        context: RunContext,
    ) -> list[ExtractionResult]:
        results: list[ExtractionResult] = []
        for rule in rules or []:
            result = self._extract_one(response, rule)
            results.append(result)
            if result.success:
                context.set(result.name, result.value, secret=result.secret)
        return results

    def _extract_one(self, response: Any, rule: Mapping[str, Any]) -> ExtractionResult:
        name = str(rule.get('name') or '').strip()
        source = str(rule.get('source') or rule.get('type') or 'json_path').lower()
        expression = str(
            rule.get('expression')
            or rule.get('json_path')
            or rule.get('header_name')
            or rule.get('pattern')
            or ''
        )
        required = bool(rule.get('required', False))
        secret = bool(rule.get('secret', False))

        if not name:
            return ExtractionResult('', source, expression, False, error='提取变量名称不能为空', required=required)

        try:
            value = self._value_from_response(response, source, expression, rule)
            if value is None:
                if 'default' in rule:
                    value = rule['default']
                else:
                    raise ValueError('未匹配到值')
            return ExtractionResult(name, source, expression, True, value=value, required=required, secret=secret)
        except Exception as exc:
            return ExtractionResult(
                name,
                source,
                expression,
                False,
                error=str(exc),
                required=required,
                secret=secret,
            )

    @staticmethod
    def _value_from_response(response: Any, source: str, expression: str, rule: Mapping[str, Any]) -> Any:
        if source in {'json', 'json_path', 'jsonpath'}:
            if not expression:
                raise ValueError('JSONPath 表达式不能为空')
            payload = response.json()
            matches = parse_json_path(expression).find(payload)
            return matches[0].value if matches else None
        if source == 'header':
            if not expression:
                raise ValueError('响应头名称不能为空')
            return response.headers.get(expression)
        if source == 'cookie':
            if not expression:
                raise ValueError('Cookie 名称不能为空')
            return response.cookies.get(expression)
        if source == 'regex':
            if not expression:
                raise ValueError('正则表达式不能为空')
            match = re.search(expression, response.text or '')
            if not match:
                return None
            group = rule.get('group', 1 if match.lastindex else 0)
            return match.group(group)
        if source == 'status_code':
            return response.status_code
        raise ValueError(f'不支持的提取器类型: {source}')
