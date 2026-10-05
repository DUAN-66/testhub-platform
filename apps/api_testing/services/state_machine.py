from __future__ import annotations

from typing import Any, Mapping

from django.db import transaction
from django.utils import timezone

from ..models import TestExecution
from .execution_events import ExecutionEventLogger


class InvalidExecutionTransition(ValueError):
    pass


class ExecutionStateMachine:
    TERMINAL_STATES = frozenset({'COMPLETED', 'FAILED', 'CANCELLED'})
    TRANSITIONS = {
        'PENDING': frozenset({'QUEUED', 'RUNNING', 'FAILED', 'CANCELLED'}),
        'QUEUED': frozenset({'RUNNING', 'FAILED', 'CANCELLED'}),
        'RUNNING': frozenset({'COMPLETED', 'FAILED', 'CANCELLED'}),
        'COMPLETED': frozenset(),
        'FAILED': frozenset(),
        'CANCELLED': frozenset(),
    }

    @classmethod
    def transition(
        cls,
        execution_id: int,
        target: str,
        *,
        updates: Mapping[str, Any] | None = None,
        message: str | None = None,
        level: str = 'INFO',
        expected_states: frozenset[str] | None = None,
    ) -> TestExecution:
        target = target.upper()
        with transaction.atomic():
            execution = TestExecution.objects.select_for_update().get(pk=execution_id)
            previous = execution.status
            if expected_states is not None and previous not in expected_states:
                raise InvalidExecutionTransition(f'执行 {execution_id} 当前为 {previous}，不能重复启动')
            if previous == target:
                return execution
            if target not in cls.TRANSITIONS.get(previous, frozenset()):
                raise InvalidExecutionTransition(f'不允许的执行状态迁移: {previous} -> {target}')

            for field, value in (updates or {}).items():
                setattr(execution, field, value)
            execution.status = target
            execution.state_version += 1
            now = timezone.now()
            if target == 'RUNNING' and execution.start_time is None:
                execution.start_time = now
            if target in cls.TERMINAL_STATES:
                execution.end_time = now
            if target == 'COMPLETED':
                execution.progress = 100
            execution.save()
            # Keep the state change and its durable event in one transaction so
            # a concurrent cancellation cannot publish events out of order.
            ExecutionEventLogger.append(
                execution_id,
                'STATE_CHANGED',
                message or f'执行状态由 {previous} 变更为 {target}',
                level=level,
                data={
                    'previous_status': previous,
                    'status': target,
                    'progress': execution.progress,
                    'state_version': execution.state_version,
                },
            )
        return execution

    @classmethod
    def update_progress(
        cls,
        execution_id: int,
        *,
        current_request: int,
        total_requests: int,
    ) -> TestExecution:
        with transaction.atomic():
            execution = TestExecution.objects.select_for_update().get(pk=execution_id)
            if execution.status != 'RUNNING':
                raise InvalidExecutionTransition(
                    f'仅 RUNNING 状态可以更新进度，当前状态为 {execution.status}'
                )
            progress = 100 if total_requests == 0 else int(current_request * 100 / total_requests)
            execution.current_request = current_request
            execution.total_requests = total_requests
            execution.progress = min(progress, 99)
            execution.save(update_fields=[
                'current_request', 'total_requests', 'progress', 'updated_at'
            ])
        return execution

