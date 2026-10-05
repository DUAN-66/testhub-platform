"""Local demonstration only: SQLite, in-process Channels and eager Celery.

Set DEMO_ASYNC=True for a separate worker using a local filesystem queue.
Set DEMO_REAL_QUEUE=True with REDIS_URL to exercise a real worker and Redis.
Never use these settings for production.
"""
from backend.test_settings import *  # noqa: F401,F403
from decouple import config

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': BASE_DIR / 'demo.sqlite3',
}}
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
MCP_ENABLED = False
if config('DEMO_ASYNC', default=False, cast=bool):
    queue_root = BASE_DIR / '.runtime' / 'celery'
    for folder in ['messages', 'control', 'processed']:
        (queue_root / folder).mkdir(parents=True, exist_ok=True)
    CELERY_TASK_ALWAYS_EAGER = False
    CELERY_BROKER_URL = 'filesystem://'
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        'data_folder_in': str(queue_root / 'messages'),
        'data_folder_out': str(queue_root / 'messages'),
        'control_folder': str(queue_root / 'control'),
        'processed_folder': str(queue_root / 'processed'),
    }
    CELERY_WORKER_SEND_TASK_EVENTS = False
    CELERY_WORKER_ENABLE_REMOTE_CONTROL = False
    CELERY_TASK_IGNORE_RESULT = True
if config('DEMO_REAL_QUEUE', default=False, cast=bool):
    CELERY_TASK_ALWAYS_EAGER = False
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    CHANNEL_LAYERS = {'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [REDIS_URL]},
    }}
