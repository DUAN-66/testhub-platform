"""Compatibility entry points for API execution.

New code should use ``apps.api_testing.engine`` for pure execution logic or
``ApiExecutionService`` when Django persistence is required.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .engine import AssertionEngine, RunContext
from .services import ApiExecutionService
from .variable_resolver import VariableResolver


def execute_assertions(response: Any, assertions: Iterable[Mapping[str, Any]] | None):
    """Preserve the original public function while delegating to the engine."""
    rules = list(assertions or [])
    response_time = next(
        (
            float(rule.get('actual_time') or 0)
            for rule in rules
            if rule.get('type') == 'response_time'
        ),
        0.0,
    )
    return [
        result.as_dict()
        for result in AssertionEngine().evaluate(
            response,
            rules,
            response_time_ms=response_time,
        )
    ]


def execute_test_suite(test_suite, environment, executed_by):
    return ApiExecutionService().execute_suite(test_suite, environment, executed_by)


def execute_api_request(api_request, environment, executed_by, *, overrides=None):
    return ApiExecutionService().execute_request(
        api_request,
        environment,
        executed_by,
        overrides=overrides,
    )


def _replace_variables(text, variables):
    context = RunContext.from_environment(variables)
    return context.render(text)


def _replace_variables_in_dict(data, variables):
    context = RunContext.from_environment(variables)
    return context.render(data)


def _resolve_variables_in_dict(data, resolver=None):
    context = RunContext(dynamic_resolver=resolver or VariableResolver())
    return context.render(data)
