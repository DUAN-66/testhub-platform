# TestHub 二次开发交付与验收

2026-10-05 新增契约变更驱动的接口回归与质量门禁，详见 [运行、设计与限制](quality-gate.md)。本页保留上一阶段的执行引擎验收记录；新增模块的 CI 证据以对应提交的 Actions artifact 为准。

个人负责在开源 TestHub 接口测试模块上完成执行引擎重构、关联接口、异步执行、状态管理、实时日志，以及契约变更驱动的回归与质量门禁开发和验证。原有用户、项目管理等基础能力复用上游实现。

## 已实现

| 能力 | 实现入口 | 验证方式 |
|---|---|---|
| 请求构造、变量替换、断言、响应提取 | `apps/api_testing/engine/` | Pytest 引擎测试、真实 HTTP 登录关联流程 |
| 套件运行上下文与敏感信息脱敏 | `services/execution.py` | 跨请求 Token 引用；历史、断言、提取、异常及嵌套序列化测试 |
| 独立 Celery 任务执行 | `tasks.py`、`services/dispatch.py` | 独立 worker 与真实 HTTP 验收；重复任务和投递失败回归 |
| 状态管理与原子启动 | `services/state_machine.py` | 合法/非法迁移、终态保护、重复启动、取消回归 |
| 持久化有序日志与 WebSocket | `consumers.py`、`services/execution_events.py` | 快照、事件、心跳和无效票据集成测试 |
| 执行界面和规则编辑 | `AutomationTesting.vue`、`components/ExecutionMonitor.vue` | 浏览器验证成功、失败、取消、非法输入和配置持久化 |
| 工程基线与 CI | 迁移、分层依赖、Compose、`quality.yml` | 全新 SQLite 迁移、无漂移检查、构建、完整回归、Compose 配置检查 |

## 本地启动

在项目根目录安装 Python 3.12 与 Node.js，执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate --settings=backend.demo_settings
.\.venv\Scripts\python.exe manage.py seed_api_demo --settings=backend.demo_settings --password 'TestHubDemo!2026'
npm ci --prefix frontend
```

分别打开四个终端，工作目录均为项目根目录：

```powershell
# 终端一：仅监听本机的被测服务
.\.venv\Scripts\python.exe scripts/demo_api.py

# 终端二：后端
$env:DJANGO_SETTINGS_MODULE='backend.demo_settings'
$env:DEMO_ASYNC='True'
.\.venv\Scripts\daphne.exe -b 127.0.0.1 -p 8000 backend.asgi:application

# 终端三：独立 worker
$env:DJANGO_SETTINGS_MODULE='backend.demo_settings'
$env:DEMO_ASYNC='True'
.\.venv\Scripts\celery.exe -A backend worker --pool=solo --concurrency=1 -l INFO --without-gossip --without-mingle --without-heartbeat

# 终端四：前端
npm run dev --prefix frontend -- --host 127.0.0.1
```

访问 `http://127.0.0.1:3000/api-testing/automation`。演示账号 `testhub_demo`，演示密码 `TestHubDemo!2026`，仅用于独立本地演示库。种子命令会保留既有账号密码，不覆盖密码不同的账号。

本地演示使用 SQLite、Celery 官方文件队列和内存 Channels；前端持续轮询补齐跨进程日志。这个模式用于复现异步执行和取消，不用于证明 Redis 或 MySQL 的生产行为。

## 自动化验证

```powershell
# 最小二开模块与相关核心回归
.\.venv\Scripts\python.exe -m pytest apps/api_testing/tests apps/core/tests.py

# 完整平台回归收集依赖与测试
.\.venv\Scripts\python.exe -m pip install -r requirements/regression.txt
.\.venv\Scripts\python.exe -m pytest --junitxml=docs/secondary-development/regression-test-results.xml

# 服务启动后的真实 HTTP / 独立 worker 验收
.\.venv\Scripts\python.exe scripts/verify_demo.py --password 'TestHubDemo!2026'

# 配置、迁移和前端
.\.venv\Scripts\python.exe manage.py check --settings=backend.test_settings
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=backend.test_settings
npm run lint --prefix frontend
npm run build --prefix frontend
```

## 验收证据

2026-10-03 本机验收结果：核心测试 40 项通过，执行引擎、服务、任务与 WebSocket 消费者合计行覆盖率 89%；完整平台回归收集 407 项，404 项通过、3 项因缺少设备或运行条件跳过。前端 lint 无错误（30 条既有警告），生产构建成功；Django 系统检查与迁移漂移检查通过。

另在全新虚拟环境中仅安装 `requirements.txt`，再次通过 40 项核心测试、Django 检查和迁移漂移检查；`pip check` 无依赖冲突。全平台可选模块回归使用 `requirements/regression.txt`，不与最小接口演示依赖混用。

真实 HTTP 服务与独立 Celery worker 验证了成功、断言失败和运行中取消。慢请求任务提交约 0.078 秒返回；取消后保存当前请求结果并跳过后续请求。该时间是单次本地演示测量，不是性能基准。浏览器另验证了断言规则非法输入提示和保存后的持久化结果。

- [真实 HTTP / worker 结果](demo-verification.json)
- 本地核心测试报告：`core-test-results.xml`
- 本地全新环境核心测试报告：`clean-environment-test-results.xml`
- 本地完整回归报告：`regression-test-results.xml`
- [真实 MySQL/Redis 容器验收](container-verification.json)
- [Redis / worker / Nginx WebSocket 验收](realtime-verification.json)
- [实际数据库与 Redis 版本](container-runtime.json)
- 本地容器状态：`container-status.json`
- 本地容器构建与最终验收日志：`container-build-and-acceptance.log`
- [容器成功执行截图](screenshots/container-success.jpg)
- [容器规则继承截图](screenshots/container-rules.jpg)
- [成功执行截图](screenshots/success.jpg)
- [断言失败截图](screenshots/failed.jpg)
- [运行中取消截图](screenshots/cancelled.jpg)
- [规则编辑截图](screenshots/rules.jpg)

## 验证边界

### 容器验收入口

`docker-compose.verify.yml` 是独立验收环境：MySQL、Redis、后端、worker、被测 HTTP 服务及 Nginx 前端全部使用独立 Compose 项目，仅绑定本机 18000/18080，不读取原有 `.env`，不挂载既有数据库目录。其中账号、密码、密钥均为演示固定值，只允许本机验收使用。

Docker 引擎正常运行后，在项目根目录执行：

```powershell
./scripts/verify_containers.ps1
```

脚本会构建前后端镜像、等待服务就绪、检查 Django 与迁移，并通过前端 Nginx 代理执行真实 MySQL/Redis 的三个 HTTP 验收场景，另验证 worker 事件经 Redis、Daphne 与 Nginx 到达 WebSocket 客户端。成功后生成 `container-verification.json` 与 `realtime-verification.json`，保留服务方便浏览器检查；无论成功与否均保存 `container-services.log`。检查完成后可执行 `docker compose -p testhub-secondary-verify -f docker-compose.verify.yml down` 停止验收环境（不删除数据卷）。CI 另加入相同的 `containers` 作业。

本机已实际构建前后端容器，并在 MySQL 8.0.46、Redis 7.4.11 下通过迁移、系统检查、HTTP 成功/断言失败/运行中取消三个场景以及 WebSocket 快照、心跳、worker 取消事件验收。演示入口为 `http://127.0.0.1:18080/api-testing/automation`。页面另修正了继承请求断言的数量和规则编辑内容显示。

2026-10-03 继续排查记录：常规 Docker Desktop 重启失败，后台日志报告无法替换 `AppData/Local/docker-secrets-engine/engine.sock`。文件与目录均带 `Encrypted` 属性，保留备份尝试失败，原目录未迁移。最终为 Docker 子进程单独设置 `LOCALAPPDATA=D:/th-docker-verify`，通过短目录链接指向项目 `.runtime/docker-short-cache`，绕过原临时目录的访问问题与 Unix 套接字路径长度限制。电脑插件观察到 Engine running，`docker version` 同时确认服务端可用；没有修改系统环境变量或 Windows 加密设置，也没有删除原有 Docker 数据。

这个启动方式只对当前 Docker 进程生效，普通重启仍可能遇到原目录问题。项目 `.runtime/docker-short-cache` 已包含此验证环境的 Docker 缓存与运行数据，勿直接删除。需要再次以此模式启动已安装的 Docker 时，可以在其退出后运行：

```powershell
$dockerPreviousLocalData=$env:LOCALAPPDATA
try {
  $env:LOCALAPPDATA='D:/th-docker-verify'
  Start-Process -FilePath 'C:/Program Files/Docker/Docker/Docker Desktop.exe' -WindowStyle Hidden
} finally {
  $env:LOCALAPPDATA=$dockerPreviousLocalData
}
```

生产配置仍使用 MySQL 与 Redis，部署入口为根目录 Compose。`quality.yml` 配置后端核心测试、前端 lint/构建、MySQL/Redis 集成与容器验收四个作业，并保存 CI 结果与日志。2026-10-05 发布前复验：完整回归 404 项通过、3 项跳过，前端 lint 无错误、构建成功。云端作业的最新结果见 [GitHub Actions](https://github.com/DUAN-66/testhub-platform/actions/workflows/quality.yml)。原始机器日志、XML 报告、数据库与缓存只在本地保留；公开仓库保留简要验收 JSON 和截图，云端原始报告通过 Actions artifacts 获取。

本机 Docker 引擎已通过临时缓存路径恢复，容器验收已实际通过。没有执行 Docker 恢复出厂设置。该验收使用独立本地数据，不代表外部生产部署、生产流量或可选 AI/手机模块已验证。

完整回归中的 Android 设备测试需要显式提供设备与业务用例，Locust 真实引擎测试需要安装对应运行环境；缺少条件时明确跳过。AI 提供商、真实手机、浏览器执行引擎与外部通知发送不属于本次接口二开验收。

OpenAPI 契约分析、受影响套件选择与质量门禁已于 2026-10-05 实现并通过 CI 验收，详见 [模块说明](quality-gate.md)。公开仓库保留 GPL-3.0 许可证及上游来源说明，采用干净快照发布，不包含运行凭据与本机配置备份。
