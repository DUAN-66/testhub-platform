from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core import signing
import pytest

from apps.api_testing.models import ApiProject, TestSuite as ApiTestSuite
from apps.api_testing.routing import websocket_urlpatterns
from apps.api_testing.services import ApiExecutionService
from apps.api_testing.services.execution_events import ExecutionEventLogger
from apps.users.models import User


@pytest.mark.django_db(transaction=True)
def test_websocket_snapshot_events_and_invalid_ticket():
    user = User.objects.create_user(username='ws-owner', password='test-pass')
    project = ApiProject.objects.create(name='ws-project', owner=user)
    suite = ApiTestSuite.objects.create(name='ws-suite', project=project, created_by=user)
    execution = ApiExecutionService().create_suite_execution(suite, user)
    ticket = signing.dumps({'execution_id': execution.id, 'user_id': user.id}, salt='api-testing-execution-ws')

    async def scenario():
        app = URLRouter(websocket_urlpatterns)
        unauthorized = WebsocketCommunicator(app, f'/ws/api-testing/executions/{execution.id}/?ticket=invalid')
        assert (await unauthorized.connect())[0] is False
        await unauthorized.disconnect()
        communicator = WebsocketCommunicator(app, f'/ws/api-testing/executions/{execution.id}/?ticket={ticket}')
        assert (await communicator.connect())[0] is True
        snapshot = await communicator.receive_json_from()
        assert snapshot['type'] == 'execution_snapshot'
        assert snapshot['logs'][0]['sequence'] == 1
        await database_sync_to_async(ExecutionEventLogger.append)(execution.id, 'TEST_EVENT', 'live event')
        event = await communicator.receive_json_from()
        assert event['type'] == 'execution_event'
        assert event['sequence'] == 2
        await communicator.send_json_to({'action': 'ping'})
        assert (await communicator.receive_json_from())['type'] == 'pong'
        await communicator.disconnect()

    async_to_sync(scenario)()
