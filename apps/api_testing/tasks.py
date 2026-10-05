from celery import shared_task

from .models import TestExecution
from .services import ApiExecutionService
from .services.execution_events import ExecutionEventLogger
from .services.state_machine import ExecutionStateMachine, InvalidExecutionTransition


@shared_task(bind=True)
def execute_test_suite_task(self, execution_id: int) -> dict:
    """Run an already-created execution; the DB record is the source of truth."""
    try:
        execution = TestExecution.objects.select_related(
            'test_suite__environment', 'executed_by'
        ).get(pk=execution_id)
    except TestExecution.DoesNotExist:
        return {'success': False, 'error': 'execution_not_found', 'execution_id': execution_id}

    if execution.status not in {'PENDING', 'QUEUED'}:
        return {'success': False, 'skipped': True, 'cancelled': execution.status == 'CANCELLED', 'execution_id': execution_id}
    if execution.celery_task_id and execution.celery_task_id != self.request.id:
        return {'success': False, 'skipped': True, 'error': 'task_id_mismatch', 'execution_id': execution_id}

    try:
        return ApiExecutionService().execute_existing_suite(execution_id)
    except InvalidExecutionTransition as exc:
        current_status = TestExecution.objects.values_list('status', flat=True).get(pk=execution_id)
        if current_status == 'CANCELLED':
            return {'success': False, 'cancelled': True, 'execution_id': execution_id}
        return {'success': False, 'skipped': True, 'execution_id': execution_id, 'status': current_status}
    except Exception as exc:
        safe_error = f'执行任务异常终止 ({type(exc).__name__})'
        try:
            ExecutionStateMachine.transition(
                execution_id,
                'FAILED',
                updates={'error_message': safe_error},
                message=safe_error,
                level='ERROR',
            )
        except InvalidExecutionTransition:
            pass
        ExecutionEventLogger.append(
            execution_id,
            'TASK_ERROR',
            safe_error,
            level='ERROR',
        )
        raise RuntimeError(safe_error) from None

