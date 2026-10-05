# TestHub QualityGate API 协议 v1

## 1. 通用约定

- 基础路径：`/api/v1`
- 数据格式：`application/json; charset=utf-8`
- 鉴权：`Authorization: Bearer <JWT>`
- 时间：ISO 8601 UTC，例如 `2026-09-28T08:30:00Z`
- 标识符：新增执行域使用 UUID；兼容资源可继续使用整数 ID
- 幂等：创建执行支持 `Idempotency-Key` 请求头
- 追踪：响应返回 `X-Request-ID`

统一成功响应：

```json
{
  "data": {},
  "meta": {"request_id": "req_01K..."}
}
```

统一错误响应：

```json
{
  "error": {
    "code": "RUN_INVALID_STATE",
    "message": "Only queued or running runs can be cancelled.",
    "details": {"status": "passed"}
  },
  "meta": {"request_id": "req_01K..."}
}
```

## 2. 兼容策略

现有 `/api/api-testing/` 接口在过渡期保留，不立即破坏前端。新增的异步执行、契约与质量门禁使用 `/api/v1/`。兼容接口内部逐步改为调用同一 service/engine，迁移完成后再发布弃用计划。

## 3. 执行 API

### 3.1 创建执行

`POST /api/v1/runs`

请求：

```json
{
  "suite_id": 42,
  "environment_id": 3,
  "trigger": {
    "type": "ci",
    "provider": "github",
    "repository": "org/service",
    "commit_sha": "7c1f...",
    "ref": "refs/pull/128/head"
  },
  "options": {
    "stop_on_failure": false,
    "timeout_ms": 30000,
    "evaluate_gate": true,
    "gate_policy_id": 8
  }
}
```

响应：`202 Accepted`

```json
{
  "data": {
    "id": "018f4e6a-...",
    "status": "queued",
    "status_url": "/api/v1/runs/018f4e6a-..."
  },
  "meta": {"request_id": "req_01K..."}
}
```

相同项目、相同 `Idempotency-Key` 与相同请求体返回原执行；相同键但请求体不同返回 `409 IDEMPOTENCY_CONFLICT`。

### 3.2 查询执行

`GET /api/v1/runs/{run_id}`

返回状态、摘要、门禁判定和步骤链接。默认不内联完整请求/响应正文。

### 3.3 查询步骤结果

`GET /api/v1/runs/{run_id}/steps?status=failed&cursor=...`

使用游标分页。敏感 header、Cookie、token 和配置的 secret 始终脱敏。

### 3.4 取消执行

`POST /api/v1/runs/{run_id}/cancel`

仅 `queued`、`running` 可取消；重复取消为幂等成功。

## 4. 契约 API

### 4.1 创建契约

`POST /api/v1/projects/{project_id}/contracts`

支持三种输入之一：`document`（JSON/YAML）、`source_url`、multipart 文件。首版支持 OpenAPI 3.0/3.1。

### 4.2 导入新版本

`POST /api/v1/contracts/{contract_id}/versions`

响应包含版本 ID、SHA-256、operation 数量；相同内容返回已有版本。

### 4.3 比较版本

`POST /api/v1/contracts/{contract_id}/diffs`

```json
{
  "from_version_id": 10,
  "to_version_id": 11,
  "include_non_breaking": true
}
```

响应摘要：

```json
{
  "data": {
    "breaking_count": 2,
    "non_breaking_count": 5,
    "changes": [
      {
        "operation": "POST /orders",
        "type": "response_required_property_added",
        "severity": "breaking",
        "path": "responses.200.schema.required[total]"
      }
    ]
  }
}
```

### 4.4 查询受影响用例

`GET /api/v1/contract-diffs/{diff_id}/impacted-cases`

返回直接关联、路径方法匹配和人工补充三类来源，供 CI 选择最小回归集。

## 5. 质量门禁 API

### 5.1 创建或更新策略

`POST /api/v1/projects/{project_id}/gate-policies`

```json
{
  "name": "PR API Gate",
  "scope": "pull_request",
  "rules": [
    {"metric": "pass_rate", "operator": ">=", "threshold": 0.98, "severity": "block"},
    {"metric": "breaking_change_count", "operator": "==", "threshold": 0, "severity": "block"},
    {"metric": "p95_regression_percent", "operator": "<=", "threshold": 20, "severity": "warn"}
  ]
}
```

### 5.2 评估执行

`POST /api/v1/runs/{run_id}/gate-evaluations`

可由执行完成事件自动触发，也允许幂等重算。响应 `result` 为 `pass`、`warn` 或 `fail`，同时列出每条规则的实际值和判定证据。

### 5.3 CI 摘要

`GET /api/v1/runs/{run_id}/ci-summary`

返回机器可读状态和 Markdown 摘要；CI 适配器负责发布 commit status/check run，核心服务不硬编码某个 CI 厂商。

## 6. 错误码

| HTTP | 错误码 | 含义 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 字段或业务参数无效 |
| 401 | `AUTHENTICATION_REQUIRED` | 未认证或 token 失效 |
| 403 | `PROJECT_ACCESS_DENIED` | 无项目权限 |
| 404 | `RESOURCE_NOT_FOUND` | 资源不存在或不可见 |
| 409 | `IDEMPOTENCY_CONFLICT` | 幂等键对应不同请求 |
| 409 | `RUN_INVALID_STATE` | 执行状态不允许当前操作 |
| 422 | `OPENAPI_PARSE_FAILED` | 契约无法解析或不受支持 |
| 429 | `RATE_LIMITED` | 请求超出限制 |
| 500 | `INTERNAL_ERROR` | 未分类服务错误 |
| 503 | `EXECUTION_QUEUE_UNAVAILABLE` | 执行队列不可用 |

## 7. Webhook 事件

首批事件：`run.started`、`run.completed`、`gate.completed`、`contract.breaking_changes_detected`。事件包含唯一 `event_id`、发生时间和资源引用；使用 HMAC-SHA256 签名，并支持接收方按 `event_id` 去重。

## 8. Phase 0 接口范围

Phase 0 不立即实现上述新业务端点，只完成 OpenAPI 文档基础设施、现有路由可启动、全新数据库可迁移和 CI 可验证。后续开发必须以本协议为评审基线；发生不兼容调整时先更新本文档。

