from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class ApiExecutionConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.execution_id = int(self.scope['url_route']['kwargs']['execution_id'])
        if not await self._can_view():
            await self.close(code=4403)
            return
        self.group_name = f'api_execution_{self.execution_id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(await self._snapshot())

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if (content or {}).get('action') == 'ping':
            await self.send_json({'type': 'pong'})

    async def execution_event(self, event):
        await self.send_json({'type': 'execution_event', **event['payload']})

    @database_sync_to_async
    def _can_view(self) -> bool:
        from django.db.models import Q

        from .models import TestExecution

        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            user_id = self._ticket_user_id()
            if user_id is None:
                return False
        else:
            user_id = user.id
        return TestExecution.objects.filter(pk=self.execution_id).filter(
            Q(test_suite__project__owner_id=user_id)
            | Q(test_suite__project__members__id=user_id)
        ).exists()

    def _ticket_user_id(self):
        from urllib.parse import parse_qs

        from django.core import signing

        query_string = self.scope.get('query_string', b'')
        if isinstance(query_string, bytes):
            query_string = query_string.decode('utf-8')
        ticket = parse_qs(query_string).get('ticket', [None])[0]
        if not ticket:
            return None
        try:
            payload = signing.loads(
                ticket,
                salt='api-testing-execution-ws',
                max_age=60,
            )
        except signing.BadSignature:
            return None
        try:
            if not isinstance(payload, dict) or int(payload.get('execution_id', 0)) != self.execution_id:
                return None
            return int(payload.get('user_id', 0)) or None
        except (TypeError, ValueError):
            return None

    @database_sync_to_async
    def _snapshot(self) -> dict:
        from .models import TestExecution

        execution = TestExecution.objects.get(pk=self.execution_id)
        logs = list(execution.logs.order_by('-sequence')[:50])
        logs.reverse()
        return {
            'type': 'execution_snapshot',
            'execution_id': execution.id,
            'status': execution.status,
            'progress': execution.progress,
            'current_request': execution.current_request,
            'total_requests': execution.total_requests,
            'logs': [
                {
                    'id': item.id,
                    'sequence': item.sequence,
                    'level': item.level,
                    'event': item.event,
                    'message': item.message,
                    'data': item.data,
                    'created_at': item.created_at.isoformat(),
                }
                for item in logs
            ],
        }

