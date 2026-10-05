"""
测试专用 Django Settings
使用 SQLite 作为测试数据库，避免依赖外部 MySQL 服务
"""
import os
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('SECRET_KEY', 'test-only-settings-key-2026-never-use-in-production-123456')
from backend.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'test_db.sqlite3',
    }
}

# 测试时禁用密码验证器，简化用户创建
AUTH_PASSWORD_VALIDATORS = []
MCP_ENABLED = True  # Test fixtures explicitly exercise the optional MCP module.

# 测试时关闭 Channels（WebSocket 需要 Redis，测试环境不依赖）
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# 测试时关闭 Celery eager 模式（同步执行）
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'

# 缓存使用本地内存
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}
