# 并发性能门禁与业务一致性验证

个人负责在现有接口引擎与契约门禁上扩展并发性能执行、服务端证据绑定、性能预算判断和业务一致性验证。复用平台的用户、项目、环境管理及 Celery 基础设施；原有 Locust 模块仍属于上游能力，本次执行器采用 Python 标准库线程池。

## 能展示的完整链路

OpenAPI 变更分析 → 受影响套件回归 → 已保存 GET/HEAD 请求的并发执行 → 服务端采集 P50/P95/P99、错误率、成功 RPS → 本次 GateRun 绑定 → 功能与性能规则共同决定 PASS/BLOCK → 不可变报告导出。

功能回归的 P95 和并发性能样本的 P95 分开显示。错误请求的耗时也参与性能分位数，吞吐量仅计算成功请求。分位数采用 nearest-rank；没有并发证据、执行未完成、配置漂移、权限撤销或样本不足时阻断。

## 业务演示与验证设计

`commerce_demo` 是新增的隔离商品/库存业务夹具，明确只用于 DEBUG 演示。baseline 故意逐条访问关联模型，用来复现 N+1；optimized 使用 `select_related('category', 'inventory')`。24 件商品返回完全相同的 JSON，业务查询数由 **49 次降至 1 次**，减少约 **97.96%**。计数仅覆盖商品查询，不包含认证与权限查询。`Server-Timing` 同时记录 SQL 耗时，不暴露 SQL 文本。

并发领取通过 MySQL 行锁、事务和 `(project, user, key)` 唯一约束保证幂等。验证同时发出 8 个同键请求，检查只有一次扣减且收据一致；随后用不同键超量领取，检查成功数等于剩余库存、最终库存为零。不同商品复用同一个键返回冲突。演示初始化不会重置已有库存或密码。

性能验收先采集 baseline，再对 optimized 执行相同的 4 用户 × 每用户 10 请求负载。真实 P95 与 RPS 写入 CI 的 `performance-verification.json`，**不承诺固定耗时提升比例**。共享 CI 机器存在噪声，验收以等价响应、49→1 查询、零错误、幂等/库存一致性和门禁结果为确定性依据。

## 运行

隔离 Docker 验收环境已经包含初始化与独立 worker：

```bash
docker compose -p testhub-secondary-verify -f docker-compose.verify.yml up --build --detach --wait
python scripts/verify_performance.py --base-url http://127.0.0.1:18080 --password 'TestHubDemo!2026'
```

脚本会为演示环境配置本次登录的认证令牌，然后完成：缺失性能证据 BLOCK → 正常 SQL 预算 PASS → SQL 预算设为 0 后 BLOCK（功能仍然通过）→ 并发库存验证。重复执行会选择仍有库存的演示商品；24 个商品都耗尽后，需要新建独立验收环境，不能重置业务数据冒充重复验证。

本地开发可执行 `python manage.py seed_performance_demo --password 'TestHubDemo!2026'`。MySQL/Redis 启动步骤参照交付文档；SQLite 单元测试不作为行锁并发正确性的证据。

界面入口为“接口测试 → 契约质量门禁”。选择 `PerformanceGate 演示`、baseline/compatible 版本，开启“并发性能门禁”，选择 optimized 请求及性能演示环境。认证变量必须已配置；不能把登录令牌发送到任意外部地址。开启 SQL 预算并设置为 1，可查看正常放行；设为 0 可查看功能通过但性能阻断。

## API 与安全边界

- `POST /api/v1/performance/`：`request_id`、`environment_id`、可选 `gate_id`、`workload`，必须携带 `Idempotency-Key`。同键同配置复用记录，配置冲突 409。
- `GET /api/v1/performance/{id}/`：仅执行人且仍有项目权限可读。无 PATCH/DELETE/上传统计入口。
- 绑定门禁的请求与环境必须属于该门禁的受影响套件；一条门禁最多绑定一个性能执行。客户端无法复用其他门禁的证据。
- 独立 `PERFORMANCE_ALLOWED_HOSTS`，生产默认空；仅精确主机授权，禁止通配符、嵌入式 URL 凭据、重定向和环境代理，保持 TLS 校验与响应大小限制。网络层仍须限制出站目的地，不能仅凭主机名阻止 DNS 重绑定。
- 每用户最多一个待执行/运行中的性能任务；每次 1–8 用户、1–50 次迭代、1–5 秒请求超时，最大 400 请求，另有预估超时预算限制。生产 worker 使用支持 Celery 硬超时的 prefork 池；Windows/solo 演示池不提供硬超时保证。
- worker 执行前后重查权限、请求/环境/目标授权指纹；重复投递只认领一次。投递失败和测量失败持久化错误码，结果不保存响应正文、请求头、令牌或原始异常。

## 范围与限制

这是有上限的闭环 HTTP 性能回归，并非完整容量压测系统。它没有恒定到达率、分布式发压、长时间稳定性或 coordinated omission 修正。连接每次独立建立；RPS 包含客户端执行与统计开销。对于真实容量结论，需要固定机器规格、分离发压机/服务端、预热、多轮交错运行及资源监控。生产目标必须由管理员明确授权，演示业务在 DEBUG=False 下不可用。

worker 被强制终止时，记录可能保留 RUNNING；该证据不能放行，需运维核实 worker 已停止后清理状态。本次没有声称实现自动故障恢复或生产容量认证。
