from __future__ import annotations

import operator
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from jsonpath_ng import parse as parse_json_path
from jsonschema import validate as validate_json_schema


@dataclass(frozen=True)
class AssertionResult:
    name: str
    type: str
    passed: bool
    expected: Any = None
    actual: Any = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'type': self.type,
            'passed': self.passed,
            'expected': self.expected,
            'actual': self.actual,
            'error': self.error,
        }


class AssertionEngine:
    OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
        'equals': operator.eq,
        'eq': operator.eq,
        'not_equals': operator.ne,
        'ne': operator.ne,
        'gt': operator.gt,
        'gte': operator.ge,
        'lt': operator.lt,
        'lte': operator.le,
    }

    def evaluate(
        self,
        response: Any,
        rules: Iterable[Mapping[str, Any]] | None,
        *,
        response_time_ms: float,
    ) -> list[AssertionResult]:
        return [self._evaluate_one(response, rule, response_time_ms) for rule in (rules or [])]

    def _evaluate_one(
        self,
        response: Any,
        rule: Mapping[str, Any],
        response_time_ms: float,
    ) -> AssertionResult:
        assertion_type = str(rule.get('type') or '').lower()
        name = str(rule.get('name') or '未命名断言')
        expected = rule.get('expected', rule.get('value'))
        actual: Any = None
        try:
            if assertion_type == 'status_code':
                actual = response.status_code
                passed = self._compare(actual, expected, rule.get('operator', 'equals'))
            elif assertion_type == 'response_time':
                actual = response_time_ms
                passed = self._compare(actual, expected, rule.get('operator', 'lte'))
            elif assertion_type == 'contains':
                actual = response.text or ''
                passed = str(expected) in actual
            elif assertion_type == 'equals':
                actual = (response.text or '').strip()
                passed = actual == str(expected).strip()
            elif assertion_type == 'regex':
                actual = response.text or ''
                passed = re.search(str(expected), actual) is not None
            elif assertion_type == 'header':
                header_name = rule.get('header_name') or rule.get('expression') or ''
                expected = rule.get('expected_value', expected)
                actual = response.headers.get(header_name)
                passed = self._compare(actual, expected, rule.get('operator', 'equals'))
            elif assertion_type in {'json_path', 'jsonpath'}:
                expression = rule.get('json_path') or rule.get('expression') or ''
                if not expression:
                    raise ValueError('JSON路径表达式不能为空')
                matches = parse_json_path(expression).find(self._response_json(response))
                actual = matches[0].value if matches else None
                passed = self._compare(actual, expected, rule.get('operator', 'equals'))
            elif assertion_type == 'json_schema':
                expected = rule.get('schema', expected)
                validate_json_schema(instance=self._response_json(response), schema=expected)
                actual = 'valid'
                passed = True
            else:
                raise ValueError(f'不支持的断言类型: {assertion_type or "<empty>"}')
            return AssertionResult(name, assertion_type, passed, expected, self._preview(actual))
        except Exception as exc:
            return AssertionResult(name, assertion_type, False, expected, self._preview(actual), str(exc))

    def _compare(self, actual: Any, expected: Any, operation: str) -> bool:
        operation = str(operation or 'equals').lower()
        if operation == 'exists':
            return actual is not None
        if operation == 'not_exists':
            return actual is None
        if operation == 'contains':
            return expected in actual if actual is not None else False
        if operation == 'matches':
            return re.search(str(expected), str(actual or '')) is not None
        comparator = self.OPERATORS.get(operation)
        if comparator is None:
            raise ValueError(f'不支持的比较操作: {operation}')
        if operation in {'gt', 'gte', 'lt', 'lte'}:
            return comparator(float(actual), float(expected))
        # Preserve the legacy JSONPath behavior where 42 and "42" are equal.
        if operation in {'equals', 'eq', 'not_equals', 'ne'}:
            return comparator(str(actual), str(expected))
        return comparator(actual, expected)

    @staticmethod
    def _preview(value: Any) -> Any:
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + '...'
        return value

    @staticmethod
    def _response_json(response: Any) -> Any:
        content_type = str(response.headers.get('content-type', '')).lower()
        if 'json' not in content_type:
            raise ValueError(f'响应不是JSON格式，Content-Type: {content_type}')
        return response.json()
