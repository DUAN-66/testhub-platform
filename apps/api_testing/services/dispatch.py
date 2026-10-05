from __future__ import annotations

import uuid
from typing import Any

from ..models import TestExecution
from .execution import ApiExecutionService
from .state_machine import ExecutionStateMachine


def dispatch_test_suite(test_suite: Any, executed_by: Any) -> TestExecution:
    """Persist, queue and dispatch a suite execution with a stable task id."""
    from ..tasks import execute_test_suite_task

    execution = ApiExecutionService().create_suite_execution(test_suite, executed_by)
    task_id = str(uuid.uuid4())
    ExecutionStateMachine.transition(
        execution.id,
        'QUEUED',
        updates={'celery_task_id': task_id},
        message='测试套件已进入 Celery 执行队列',
    )
    try:
        execute_test_suite_task.apply_async(args=[execution.id], task_id=task_id)
    except Exception as exc:
        ExecutionStateMachine.transition(
            execution.id,
            'FAILED',
            updates={'error_message': f'Celery 任务投递失败: {exc}'},
            message=f'Celery 任务投递失败: {exc}',
            level='ERROR',
        )
        raise
    return TestExecution.objects.get(pk=execution.id)

