# TestHub QualityGate 目标架构

## 1. 项目定位

项目名称暂定为 **TestHub QualityGate**：基于 TestHub 二次开发的 OpenAPI 驱动接口持续测试与发布质量门禁平台。

重点能力是“契约变更发现 → 受影响用例选择 → 异步执行 → 质量规则判定 → CI 反馈”的闭环，而不是继续堆叠测试类型。

## 2. 逻辑架构

```mermaid
flowchart LR
    U[测试/开发人员] --> FE[Vue 3 控制台]
    CI[GitHub Actions / Jenkins] --> API[Django REST API]
    FE --> API

    subgraph Control[控制面]
      API --> AUTH[用户与项目权限]
      API --> CASES[API 用例/套件]
      API --> CONTRACT[OpenAPI 契约中心]
      API --> GATE[质量门禁服务]
      API --> REPORT[报告与趋势]
    end

    subgraph Execution[执行面]
      API --> Q[(Redis / Celery Queue)]
      Q --> WORKER[API Runner Worker]
      WORKER --> CTX[Run Context]
      CTX --> EXTRACT[变量提取器]
      CTX --> ASSERT[断言引擎]
      CTX --> REDACT[敏感信息脱敏]
      WORKER --> SUT[被测服务]
    end

    CONTRACT --> SNAP[(契约快照/差异)]
    CONTRACT --> CASES
    WORKER --> DB[(MySQL)]
    AUTH --> DB
    CASES --> DB
    GATE --> DB
    REPORT --> DB
    WORKER --> ART[(Allure/JSON 制品)]
    GATE --> RESULT[Commit Status / Webhook]
```

## 3. 后端模块边界

```text
apps/
├── api_testing/                 # 保留资源模型与兼容接口
│   ├── engine/
│   │   ├── context.py           # 套件级变量、Cookie、步骤输出
│   │   ├── request_builder.py   # URL/header/query/body 构造
│   │   ├── extractors.py        # JSONPath/header/regex 提取
│   │   ├── assertions.py        # 状态、Schema、JSONPath、耗时等
│   │   ├── hooks.py             # 受控的前后置扩展点
│   │   ├── runner.py            # 单请求执行
│   │   └── suite_runner.py      # 顺序编排与失败策略
│   ├── services/                # 应用服务和事务边界
│   └── tasks.py                 # Celery 异步入口
├── contracts/                   # 新增：OpenAPI 契约中心
│   ├── importer.py
│   ├── diff.py
│   ├── impact.py
│   └── models.py
└── quality_gates/               # 新增：质量门禁
    ├── evaluator.py
    ├── policies.py
    ├── publishers.py
    └── models.py
```

视图层只负责鉴权、校验与序列化；业务规则放在 service；HTTP 执行只出现在 engine；异步任务只负责调用 service，并使用执行 ID 保证幂等。

## 4. 关键运行时流程

```mermaid
sequenceDiagram
    participant C as CI/用户
    participant A as REST API
    participant Q as Celery/Redis
    participant W as Runner Worker
    participant S as 被测服务
    participant G as Quality Gate

    C->>A: POST /api/v1/runs
    A->>A: 创建 queued Run（幂等键）
    A->>Q: enqueue(run_id)
    A-->>C: 202 + run_id
    Q->>W: execute(run_id)
    loop 套件步骤
      W->>W: 渲染上下文变量
      W->>S: HTTP request
      S-->>W: response
      W->>W: 提取变量 + 执行断言 + 脱敏
    end
    W->>G: 汇总运行指标
    G->>G: 按策略计算 pass/warn/fail
    G-->>A: 保存结果与证据
    C->>A: GET /api/v1/runs/{id}
    A-->>C: 状态、摘要、门禁结果
```

## 5. 非功能约束

- 安全：凭据加密存储；日志、响应与报告统一脱敏；脚本钩子默认关闭或沙箱运行。
- 可靠性：执行任务幂等；worker 可重试；同一执行只能发生合法状态迁移。
- 可观测性：每次执行具备 `run_id`、`trace_id`、耗时、失败阶段和结构化错误码。
- 可扩展性：提取器、断言器、门禁规则采用注册机制，不在视图中增加分支。
- 可测试性：engine 不依赖 Django request，可用纯单元测试覆盖；外部 HTTP 使用 mock/fixture。
- 兼容性：现有 `/api/api-testing/` 在过渡期保留；新增能力统一放到 `/api/v1/`。

## 6. 二开边界

保留 TestHub 的用户、项目、基础 API 资源、报告页面和通知能力。Phase 1 以后只深改 `api_testing`，新增 `contracts` 与 `quality_gates`。其他大型模块仅作为集成方，不在求职项目主线中扩建。

