from __future__ import annotations

import logging
from typing import Any, Mapping

from asgiref.sync import async_to_sync
from django.db import transaction
from django.db.models import Max

from ..models import TestExecution, TestExecutionLog

logger = logging.getLogger(__name__)


class ExecutionEventLogger:
    """Persist ordered events and best-effort publish them to Channels."""

    @classmethod
    def append(
        cls,
        execution_id: int,
        event: str,
        message: str,
        *,
        level: str = 'INFO',
        data: Mapping[str, Any] | None = None,
    ) -> TestExecutionLog:
        with transaction.atomic():
            TestExecution.objects.select_for_update().get(pk=execution_id)
            last_sequence = (
                TestExecutionLog.objects.filter(execution_id=execution_id)
                .aggregate(value=Max('sequence'))['value']
                or 0
            )
            entry = TestExecutionLog.objects.create(
                execution_id=execution_id,
                sequence=last_sequence + 1,
                level=level,
                event=event,
                message=message,
                data=dict(data or {}),
            )
            payload = cls.serialize(entry)
            transaction.on_commit(lambda: cls.publish(execution_id, payload))
        return entry

    @staticmethod
    def serialize(entry: TestExecutionLog) -> dict[str, Any]:
        return {
            'id': entry.id,
            'execution_id': entry.execution_id,
            'sequence': entry.sequence,
            'level': entry.level,
            'event': entry.event,
            'message': entry.message,
            'data': entry.data,
            'created_at': entry.created_at.isoformat(),
        }

    @staticmethod
    def publish(execution_id: int, payload: Mapping[str, Any]) -> None:
        try:
            from channels.layers import get_channel_layer

            channel_layer = get_channel_layer()
            if channel_layer is None:
                return
            async_to_sync(channel_layer.group_send)(
                f'api_execution_{execution_id}',
                {'type': 'execution_event', 'payload': dict(payload)},
            )
        except Exception as exc:  # pragma: no cover - Redis outage is best effort
            logger.warning('接口执行日志实时推送失败 execution=%s: %s', execution_id, exc)

