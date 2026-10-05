from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class DynamicResolver(Protocol):
    def resolve(self, text: str) -> str: ...


_VARIABLE_PATTERN = re.compile(r'\{\{\s*([^{}]+?)\s*\}\}')
_SECRET_NAME_PATTERN = re.compile(
    r'(authorization|password|passwd|secret|token|api[_-]?key|cookie)',
    re.IGNORECASE,
)


def _environment_value(value: Any) -> Any:
    """Normalize both legacy scalars and Postman-like variable objects."""
    if not isinstance(value, Mapping):
        return value
    if 'currentValue' in value and value['currentValue'] not in (None, ''):
        return value['currentValue']
    if 'initialValue' in value:
        return value['initialValue']
    if 'value' in value:
        return value['value']
    return value


@dataclass
class RunContext:
    """Mutable state shared by every step in one suite run."""

    variables: dict[str, Any] = field(default_factory=dict)
    secret_names: set[str] = field(default_factory=set)
    dynamic_resolver: DynamicResolver | None = None
    step_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    redaction_values: set[str] = field(default_factory=set)

    @classmethod
    def from_environment(
        cls,
        variables: Mapping[str, Any] | None,
        *,
        dynamic_resolver: DynamicResolver | None = None,
    ) -> 'RunContext':
        normalized: dict[str, Any] = {}
        secret_names: set[str] = set()
        for name, raw_value in (variables or {}).items():
            normalized[name] = _environment_value(raw_value)
            if (
                _SECRET_NAME_PATTERN.search(name)
                or isinstance(raw_value, Mapping)
                and (raw_value.get('secret') is True or raw_value.get('type') == 'secret')
            ):
                secret_names.add(name)
        return cls(
            variables=normalized,
            secret_names=secret_names,
            dynamic_resolver=dynamic_resolver,
        )

    def set(self, name: str, value: Any, *, secret: bool = False) -> None:
        self.variables[name] = value
        if secret or _SECRET_NAME_PATTERN.search(name):
            self.secret_names.add(name)

    def update(self, values: Mapping[str, Any], *, secret_names: set[str] | None = None) -> None:
        for name, value in values.items():
            self.set(name, value, secret=name in (secret_names or set()))

    def record_step(self, step_key: str, output: Mapping[str, Any]) -> None:
        self.step_outputs[str(step_key)] = copy.deepcopy(dict(output))

    def render_text(self, value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1).strip()
            if name not in self.variables:
                return match.group(0)
            current = self.variables[name]
            return '' if current is None else str(current)

        rendered = _VARIABLE_PATTERN.sub(replace, value)
        if self.dynamic_resolver:
            rendered = self.dynamic_resolver.resolve(rendered)
        return rendered

    def render(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.render_text(value)
        if isinstance(value, dict):
            return {key: self.render(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.render(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.render(item) for item in value)
        return value

    def snapshot(self, *, masked: bool = True) -> dict[str, Any]:
        snapshot = copy.deepcopy(self.variables)
        if masked:
            for name in self.secret_names:
                if name in snapshot:
                    snapshot[name] = '******'
        return snapshot
