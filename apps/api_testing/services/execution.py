from __future__ import annotations

import copy
import json
import re
from typing import Any, Mapping

from apps.core.variable_resolver import VariableResolver

from ..engine import ApiRunner, RunContext
from ..models import RequestHistory, TestExecution
from .execution_events import ExecutionEventLogger
from .state_machine import ExecutionStateMachine, InvalidExecutionTransition
from .http_transport import RestrictedHttpClient


_SENSITIVE_KEY = re.compile(
    r'(authorization|password|passwd|secret|token|api[_-]?key|cookie|set-cookie)',
    re.IGNORECASE,
)


class ApiExecutionService:
    """Django persistence boundary around the framework-independent runner."""

    def __init__(self, *, runner: ApiRunner | None = None) -> None:
        self.runner = runner or ApiRunner(http_client=RestrictedHttpClient())

    def create_context(self, environment: Any = None) -> RunContext:
        variables = environment.variables if environment else {}
        return RunContext.from_environment(variables, dynamic_resolver=VariableResolver())

    @staticmethod
    def validate_environment_access(environment: Any, user: Any) -> None:
        if environment is None:
            return
        if environment.scope == 'GLOBAL' and environment.created_by_id != user.id:
            raise ValueError('无权使用其他用户的全局环境')
        if environment.scope == 'LOCAL' and (not environment.project_id or
                (environment.project.owner_id != user.id and not environment.project.members.filter(pk=user.id).exists())):
            raise ValueError('无权使用该项目环境')

    @classmethod
    def validate_suite_access(cls, suite: Any, user: Any, environment: Any = None) -> None:
        if not user.is_active or (suite.project.owner_id != user.id and not suite.project.members.filter(pk=user.id).exists()):
            raise ValueError('无权执行该项目套件')
        environment = environment if environment is not None else suite.environment
        cls.validate_environment_access(environment, user)
        if environment and environment.scope == 'LOCAL' and environment.project_id != suite.project_id:
            raise ValueError('执行环境必须属于当前项目')

    def execute_request(
        self,
        api_request: Any,
        environment: Any,
        executed_by: Any,
        *,
        overrides: Mapping[str, Any] | None = None,
        context: RunContext | None = None,
        assertions: list[Mapping[str, Any]] | None = None,
        extractors: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.validate_environment_access(environment, executed_by)
        context = context or self.create_context(environment)
        definition = self._request_definition(api_request, overrides)
        effective_assertions = list(assertions if assertions is not None else definition.pop('assertions', []))
        effective_extractors = list(extractors if extractors is not None else definition.pop('extractors', []))
        run = self.runner.run(
            definition,
            context,
            assertions=effective_assertions,
            extractors=effective_extractors,
        )

        request_snapshot = run.request.snapshot() if run.request else definition
        response_snapshot = run.response_snapshot()
        # Collect literal credentials as well as variable-based secrets before
        # serializing assertions, response text or exception messages.
        self._redact(context.render(definition), context)
        self._redact(response_snapshot, context)
        assertion_results = self._redact([item.as_dict() for item in run.assertions], context)
        extraction_results = self._redact([item.as_dict() for item in run.extractions], context)
        error = self._redact(run.error or '', context)
        request_snapshot = self._redact(request_snapshot, context)
        response_snapshot = self._redact(response_snapshot, context)

        history = RequestHistory.objects.create(
            request=api_request,
            environment=environment,
            request_data=request_snapshot,
            response_data=response_snapshot,
            status_code=run.response.status_code if run.response is not None else None,
            response_time=run.response_time_ms,
            error_message=error,
            assertions_results=assertion_results,
            executed_by=executed_by,
        )

        status_code = run.response.status_code if run.response is not None else None
        context.record_step(
            str(api_request.pk),
            {
                'status_code': status_code,
                'response_time': run.response_time_ms,
                'passed': run.passed,
                'extractions': extraction_results,
            },
        )
        return {
            'success': run.error is None,
            'passed': run.passed,
            'history_id': history.id,
            'status_code': status_code,
            'response_time': run.response_time_ms,
            'assertions_results': assertion_results,
            'extractions_results': extraction_results,
            'response_data': response_snapshot,
            'request_data': request_snapshot,
            'error': error or self._failure_message(assertion_results, extraction_results),
            'context': context.snapshot(),
        }

    def create_suite_execution(self, test_suite: Any, executed_by: Any) -> TestExecution:
        """Create the durable command record before sync or async dispatch."""
        self.validate_suite_access(test_suite, executed_by)
        execution = TestExecution.objects.create(
            test_suite=test_suite,
            status='PENDING',
            executed_by=executed_by,
            total_requests=test_suite.testsuiterequest_set.filter(enabled=True).count(),
        )
        ExecutionEventLogger.append(
            execution.id,
            'EXECUTION_CREATED',
            '测试套件执行记录已创建',
            data={'status': 'PENDING', 'test_suite_id': test_suite.id},
        )
        return execution

    def execute_suite(self, test_suite: Any, environment: Any, executed_by: Any) -> dict[str, Any]:
        """Synchronous compatibility entry point, backed by the same state machine."""
        execution = self.create_suite_execution(test_suite, executed_by)
        return self.execute_existing_suite(execution.id, environment=environment)

    def execute_existing_suite(
        self,
        execution_id: int,
        *,
        environment: Any = None,
    ) -> dict[str, Any]:
        """Execute a persisted command. Used by both Celery and compatibility calls."""
        execution = TestExecution.objects.select_related(
            'test_suite__environment', 'executed_by'
        ).get(pk=execution_id)
        if execution.status not in {'PENDING', 'QUEUED'}:
            raise InvalidExecutionTransition(
                f'执行 {execution.id} 当前为 {execution.status}，不能重复启动'
            )
        test_suite = execution.test_suite
        environment = environment if environment is not None else test_suite.environment
        executed_by = execution.executed_by
        # Recheck after queueing: membership and environment bindings can change.
        self.validate_suite_access(test_suite, executed_by, environment)
        ExecutionStateMachine.transition(
            execution.id,
            'RUNNING',
            message='Celery Worker 已开始执行测试套件',
            expected_states=frozenset({'PENDING', 'QUEUED'}),
        )
        context = self.create_context(environment)
        suite_requests = list(
            test_suite.testsuiterequest_set.filter(enabled=True)
            .select_related('request')
            .order_by('order')
        )
        execution.total_requests = len(suite_requests)
        execution.save(update_fields=['total_requests', 'updated_at'])

        results: list[dict[str, Any]] = []
        passed_count = 0
        failed_count = 0
        try:
            for index, suite_request in enumerate(suite_requests, start=1):
                execution.refresh_from_db(fields=['status'])
                if execution.status == 'CANCELLED':
                    ExecutionEventLogger.append(
                        execution.id,
                        'EXECUTION_CANCELLED',
                        '检测到取消信号，后续请求不再执行',
                        level='WARNING',
                    )
                    return {
                        'success': False,
                        'cancelled': True,
                        'execution_id': execution.id,
                        'results': results,
                    }
                api_request = suite_request.request
                ExecutionEventLogger.append(
                    execution.id,
                    'REQUEST_STARTED',
                    f'开始执行请求 {index}/{len(suite_requests)}: {api_request.name}',
                    data={
                        'request_id': api_request.id,
                        'request_name': api_request.name,
                        'current_request': index,
                        'total_requests': len(suite_requests),
                    },
                )
                combined_assertions = [
                    *(api_request.assertions or []),
                    *(suite_request.assertions or []),
                ]
                combined_extractors = [
                    *(api_request.extractors or []),
                    *(suite_request.extractors or []),
                ]
                result = self.execute_request(
                    api_request,
                    environment,
                    executed_by,
                    context=context,
                    assertions=combined_assertions,
                    extractors=combined_extractors,
                )
                passed_count += int(result['passed'])
                failed_count += int(not result['passed'])
                results.append(
                    {
                        'name': api_request.name,
                        'method': result['request_data'].get('method', api_request.method),
                        'url': result['request_data'].get('url', api_request.url),
                        'status_code': result['status_code'],
                        'response_time': result['response_time'],
                        'passed': result['passed'],
                        'error': result['error'],
                        'assertions_results': result['assertions_results'],
                        'extractions_results': result['extractions_results'],
                    }
                )
                execution.passed_requests = passed_count
                execution.failed_requests = failed_count
                execution.results = results
                execution.current_request = index
                execution.save(update_fields=[
                    'passed_requests', 'failed_requests', 'results', 'current_request', 'updated_at'
                ])
                execution.refresh_from_db(fields=['status'])
                if execution.status == 'CANCELLED':
                    ExecutionEventLogger.append(
                        execution.id,
                        'EXECUTION_CANCELLED',
                        '当前请求结束后停止执行，后续请求已跳过',
                        level='WARNING',
                    )
                    return {
                        'success': False,
                        'cancelled': True,
                        'execution_id': execution.id,
                        'results': results,
                    }
                ExecutionStateMachine.update_progress(
                    execution.id,
                    current_request=index,
                    total_requests=len(suite_requests),
                )
                ExecutionEventLogger.append(
                    execution.id,
                    'REQUEST_FINISHED',
                    f"请求执行{'通过' if result['passed'] else '失败'}: {api_request.name}",
                    level='INFO' if result['passed'] else 'ERROR',
                    data={
                        'request_id': api_request.id,
                        'request_name': api_request.name,
                        'passed': result['passed'],
                        'status_code': result['status_code'],
                        'response_time': result['response_time'],
                        'progress': min(int(index * 100 / max(len(suite_requests), 1)), 99),
                    },
                )
        except Exception as exc:
            updates = {
                'results': results,
                'passed_requests': passed_count,
                'failed_requests': failed_count + 1,
                'error_message': self._redact(str(exc), context),
            }
            try:
                ExecutionStateMachine.transition(
                    execution.id,
                    'FAILED',
                    updates=updates,
                    message=self._redact(f'测试套件执行异常: {exc}', context),
                    level='ERROR',
                )
            except InvalidExecutionTransition:
                if TestExecution.objects.values_list('status', flat=True).get(pk=execution.id) != 'CANCELLED':
                    raise
                ExecutionEventLogger.append(execution.id, 'EXECUTION_CANCELLED', '取消后当前请求已结束', level='WARNING')
                return {'success': False, 'cancelled': True, 'execution_id': execution.id, 'results': results}
            return {'success': False, 'execution_id': execution.id, 'error': self._redact(str(exc), context), 'results': results}

        final_status = 'COMPLETED' if failed_count == 0 else 'FAILED'
        try:
            ExecutionStateMachine.transition(
                execution.id,
                final_status,
                updates={
                    'passed_requests': passed_count,
                    'failed_requests': failed_count,
                    'results': results,
                    'progress': 100,
                    'error_message': '' if failed_count == 0 else f'{failed_count} 个请求未通过',
                },
                message=(
                    f'测试套件执行完成，共 {len(suite_requests)} 个请求，'
                    f'{passed_count} 个通过，{failed_count} 个失败'
                ),
                level='INFO' if failed_count == 0 else 'ERROR',
            )
        except InvalidExecutionTransition:
            if TestExecution.objects.values_list('status', flat=True).get(pk=execution.id) != 'CANCELLED':
                raise
            return {'success': False, 'cancelled': True, 'execution_id': execution.id, 'results': results}
        return {
            'success': True,
            'execution_id': execution.id,
            'passed_count': passed_count,
            'failed_count': failed_count,
            'total_count': execution.total_requests,
            'results': results,
            'context': context.snapshot(),
        }

    @staticmethod
    def _request_definition(api_request: Any, overrides: Mapping[str, Any] | None) -> dict[str, Any]:
        definition = {
            'method': api_request.method,
            'url': api_request.url,
            'headers': copy.deepcopy(api_request.headers),
            'params': copy.deepcopy(api_request.params),
            'body': copy.deepcopy(api_request.body),
            'auth': copy.deepcopy(api_request.auth),
            'assertions': copy.deepcopy(api_request.assertions),
            'extractors': copy.deepcopy(api_request.extractors),
            'timeout': 30,
        }
        allowed = {
            'method', 'url', 'headers', 'params', 'body', 'auth', 'assertions', 'extractors', 'timeout'
        }
        for key, value in (overrides or {}).items():
            if key in allowed:
                definition[key] = copy.deepcopy(value)
        return definition

    @classmethod
    def _redact(cls, value: Any, context: RunContext) -> Any:
        if value is None:
            return None
        def collect(item: Any, key: str = '') -> None:
            if isinstance(item, dict):
                for child_key, child in item.items():
                    collect(child, str(child_key))
            elif isinstance(item, list):
                for child in item:
                    if isinstance(child, dict) and _SENSITIVE_KEY.search(str(child.get('key', ''))):
                        collect(child.get('value'), 'secret')
                    else:
                        collect(child, key)
            elif isinstance(item, str) and item and _SENSITIVE_KEY.search(key):
                context.redaction_values.add(item)

        collect(value)
        secret_values = context.redaction_values | {
            str(context.variables[name])
            for name in context.secret_names
            if name in context.variables and context.variables[name] not in (None, '')
        }

        def visit(item: Any, key: str = '') -> Any:
            if _SENSITIVE_KEY.search(key):
                return '******'
            if isinstance(item, dict):
                return {child_key: visit(child, str(child_key)) for child_key, child in item.items()}
            if isinstance(item, list):
                return [visit(child) for child in item]
            if isinstance(item, str):
                redacted = item
                for secret in sorted(secret_values, key=len, reverse=True):
                    redacted = redacted.replace(secret, '******')
                    redacted = redacted.replace(json.dumps(secret, ensure_ascii=True)[1:-1], '******')
                return redacted
            return item

        return visit(value)

    @staticmethod
    def _failure_message(
        assertions: list[Mapping[str, Any]],
        extractions: list[Mapping[str, Any]],
    ) -> str:
        for result in assertions:
            if not result.get('passed'):
                return result.get('error') or f"断言失败: {result.get('name', '未命名断言')}"
        for result in extractions:
            if result.get('required') and not result.get('success'):
                return result.get('error') or f"必需变量提取失败: {result.get('name')}"
        return ''
