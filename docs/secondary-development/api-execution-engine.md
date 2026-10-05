# 统一接口执行引擎

## 1. 分层

```text
View / Scheduled Task
        |
ApiExecutionService        Django 模型、历史记录、套件执行记录、脱敏
        |
ApiRunner                  单步骤生命周期编排
  |-- RunContext           套件共享变量与步骤输出
  |-- RequestBuilder       URL/Header/Query/Auth/Body 构造
  |-- ExtractorEngine      响应取值并写回上下文
  `-- AssertionEngine      统一断言与结构化结果
```

`engine/` 不依赖 Django，可以通过假 HTTP Client 做纯单元测试。`services/` 是唯一允许访问接口测试 ORM 模型的执行层。

## 2. 上下文变量

环境变量兼容普通对象和 Postman 风格对象：

```json
{
  "base_url": "https://api.example.com",
  "tenant": {"currentValue": "qa", "initialValue": "dev"},
  "api_token": {"value": "secret", "type": "secret"}
}
```

URL、Header、Query 和 Body 都支持 `{{variable_name}}`。未定义变量原样保留，便于快速发现拼写和配置错误。套件只创建一个 `RunContext`，提取成功的值立即写入并可供后续步骤使用。

名称包含 `authorization`、`password`、`secret`、`token`、`api_key`、`cookie`，或显式声明 `secret: true` 的变量，在上下文快照和历史记录中显示为 `******`。

## 3. 提取器协议

提取规则保存在 `ApiRequest.extractors` 或 `TestSuiteRequest.extractors`。套件步骤规则追加到接口规则之后执行。

```json
{
  "name": "access_token",
  "source": "json_path",
  "expression": "$.data.access_token",
  "required": true,
  "secret": true,
  "default": null
}
```

支持的 `source`：

| 类型 | expression | 说明 |
|---|---|---|
| `json_path` | `$.data.id` | 提取首个 JSONPath 匹配 |
| `header` | `X-Request-ID` | 提取响应头 |
| `cookie` | `sessionid` | 提取 Cookie |
| `regex` | `token=(\w+)` | 默认取第一个分组，可用 `group` 指定 |
| `status_code` | 空 | 提取 HTTP 状态码 |

普通提取失败只记录证据；`required: true` 的提取失败会让当前步骤失败。设置 `default` 后，未匹配时写入默认值。

## 4. 断言协议

```json
{
  "name": "订单创建成功",
  "type": "json_path",
  "expression": "$.data.status",
  "operator": "equals",
  "expected": "created"
}
```

支持类型：`status_code`、`response_time`、`contains`、`equals`、`regex`、`header`、`json_path`、`json_schema`。

通用比较操作：`equals/eq`、`not_equals/ne`、`gt`、`gte`、`lt`、`lte`、`contains`、`matches`、`exists`、`not_exists`。旧套件状态码断言中的 `value` 字段继续兼容。

JSON Schema 示例：

```json
{
  "type": "json_schema",
  "schema": {
    "type": "object",
    "required": ["data"],
    "properties": {"data": {"type": "object"}}
  }
}
```

## 5. 执行结果

单步骤结果包含：请求快照、响应快照、耗时、结构化断言结果、结构化提取结果和错误。步骤通过条件为：

1. 请求构造和 HTTP 调用没有异常；
2. 所有断言通过；
3. 所有 `required` 提取器成功。

历史记录会统一脱敏；原始 secret 只存在于当前运行上下文内，不写入上下文快照或结构化提取结果。

## 6. 当前边界

- 前后置脚本字段仍不执行，避免直接运行不受控代码；后续通过受限 Hook 接口实现。
- 当前执行仍为同步 HTTP；迁移到 Celery 时复用相同 service/engine，不复制执行逻辑。
- 暂不处理 WebSocket 请求和 multipart 文件上传，这两类协议将通过独立 transport 适配器接入。
