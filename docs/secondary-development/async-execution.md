# Celery 异步执行、状态机与实时日志

## 执行链路

```text
POST /test-suites/{id}/execute/
          |
          v
创建 TestExecution(PENDING)
          |
          v
状态机 -> QUEUED，并持久化 celery_task_id
          |
          v
Celery Worker -> RUNNING -> COMPLETED / FAILED
          |
          +--> TestExecutionLog（有序、可追溯）
          +--> Channels / Redis（实时推送）
```

HTTP 接口只负责创建任务和投递 Celery，返回 `202 Accepted`。Worker 仍调用
`ApiExecutionService`，不会维护第二套请求执行、断言或提取逻辑。

## 状态机

允许的迁移如下：

- `PENDING -> QUEUED | RUNNING | FAILED | CANCELLED`
- `QUEUED -> RUNNING | FAILED | CANCELLED`
- `RUNNING -> COMPLETED | FAILED | CANCELLED`
- `COMPLETED / FAILED / CANCELLED` 为终态

所有迁移在数据库事务和行锁内完成，非法迁移返回冲突，`state_version` 用于前端识别状态变化。

## HTTP 协议

- `POST /api/api-testing/test-suites/{suite_id}/execute/`：投递任务，返回执行记录和 `celery_task_id`。
- `GET /api/api-testing/test-executions/{id}/`：查询状态、进度和结果。
- `GET /api/api-testing/test-executions/{id}/logs/?after=10&limit=200`：按序号增量拉取日志。
- `POST /api/api-testing/test-executions/{id}/cancel/`：持久化取消信号，并尽力撤销队列任务。
- `POST /api/api-testing/test-executions/{id}/realtime-ticket/`：获取 60 秒有效的 WebSocket 票据。

## WebSocket 协议

连接地址由票据接口返回，格式为：

```text
/ws/api-testing/executions/{execution_id}/?ticket={ticket}
```

连接成功后首先收到 `execution_snapshot`，包括当前状态、进度以及最近 50 条日志；之后收到
`execution_event` 增量事件。票据绑定执行 ID 和当前用户，避免把长期 JWT 暴露在 URL 中。

Redis 或 WebSocket 临时不可用时，日志仍会落库，前端可以无损降级到 `logs` 轮询接口。

## 取消语义

取消是协作式的：排队任务会收到 Celery revoke；运行中的 HTTP 请求不会被强杀，而是在当前请求结束后
读取数据库取消状态并停止后续步骤，从而避免中途破坏历史记录和共享上下文。

## 运行方式

```bash
celery -A backend worker -l info
daphne -b 0.0.0.0 -p 8000 backend.asgi:application
```

生产环境需要 Redis 同时承担 Celery broker/result backend 和 Channels layer。
