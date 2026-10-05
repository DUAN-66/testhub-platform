# Phase 0：工程基线整改清单

## 1. 目标与边界

Phase 0 的目标不是新增业务功能，而是把当前仓库修复为一个可重复安装、可迁移、可测试、可构建、可部署的二开基线。完成后才进入接口执行引擎、OpenAPI 契约测试和质量门禁开发。

本阶段不重构 APP 自动化、UI 自动化、AI 需求分析、缺陷/评审、MCP、数据工厂和复杂权限模型，也不改变已有业务接口语义。

## 2. 已确认的基线问题

| 编号 | 问题 | 影响 | 优先级 |
|---|---|---|---|
| P0-01 | 多数 Django 应用没有初始迁移，现有性能测试迁移依赖不存在的 `api_testing.0001_initial` | 无法创建数据库、运行后端测试 | P0 |
| P0-02 | `pytest.ini` 配置了 Django，但依赖中未声明 `pytest-django` | 新环境无法按项目配置运行测试 | P0 |
| P0-03 | 根目录缺少 README 所述后端 Dockerfile 与 Compose 编排 | 无法一条命令复现完整环境 | P0 |
| P0-04 | 前端缺少有效 ESLint 配置，lint 脚本默认修改文件 | CI 无法执行只读代码检查 | P0 |
| P0-05 | `.env.bak` 被版本控制且含疑似真实凭据 | 凭据泄漏风险 | P0 |
| P0-06 | 未配置生产 CORS 时默认允许任意来源 | 生产安全默认值不合理 | P0 |
| P0-07 | 依赖全集耦合 API、浏览器、移动端、OCR 与 AI | 安装体积大、失败面广、CI 缓慢 | P1 |
| P0-08 | 缺少持续集成工作流 | 回归质量依赖人工 | P1 |
| P0-09 | API 执行器核心路径缺少独立自动化测试 | 后续重构无安全网 | P1 |
| P0-10 | README、实际目录和启动命令不一致 | 新成员难以复现 | P1 |

## 3. 实施清单与验收标准

### A. 数据库迁移

- [x] 为所有含模型的本地应用生成并提交初始迁移。
- [x] 修正 `perf_testing`、`monitor`、`mcp` 与核心应用之间的依赖顺序。
- [x] 使用全新 SQLite 测试库执行迁移。
- [x] 确保 `makemigrations --check --dry-run` 无漂移。

验收命令：

```bash
python manage.py makemigrations --check --dry-run --settings=backend.test_settings
python manage.py migrate --noinput --settings=backend.test_settings
```

### B. 依赖分层

- [x] `requirements/base.txt`：Django、DRF、数据库、鉴权与通用工具。
- [x] `requirements/api.txt`：接口测试与报告能力。
- [x] `requirements/perf.txt`：性能测试引擎（含 Locust）。
- [x] `requirements/web-ui.txt`：Playwright、Selenium、Browser Use。
- [x] `requirements/mobile.txt`：Airtest、OCR、OpenCV。
- [x] `requirements/ai.txt`：模型 SDK 与 LangChain。
- [x] `requirements/dev.txt`：pytest、pytest-django、覆盖率和静态检查。
- [x] 根 `requirements.txt` 保留兼容入口，并明确完整安装方式。

验收：最小开发依赖可完成 Django check、迁移和核心测试；可选能力按需安装。

### C. 安全基线

- [x] 删除被跟踪的备份环境文件并加入忽略规则。
- [x] README 明确要求轮换已经暴露过的数据库凭据。
- [x] 生产环境 CORS 默认拒绝，仅显式配置允许来源。
- [x] Redis 默认连接不内置密码。
- [ ] CI 增加敏感信息扫描（后续可接入 gitleaks）。

### D. 容器化与本地启动

- [x] 增加后端容器镜像定义。
- [x] 增加根 Compose：backend、frontend、mysql、redis、worker。
- [x] 增加健康检查、环境变量样例和初始化说明。
- [x] 容器不以内置密钥或默认生产口令启动。

验收：新环境复制 `.env.example` 后可启动核心栈，并访问 `/api/docs/`。

### E. 测试与 CI

- [ ] 后端：Django system check、迁移漂移检查、pytest（check/迁移及 33 个核心与 API 断言测试已通过；全量可选模块测试待完整依赖 CI 验证）。
- [x] 前端：无修改 lint、生产构建。
- [ ] 为 API runner 建立变量替换、请求构造、断言、异常与脱敏测试骨架（已先补断言回归测试）。
- [x] GitHub Actions 对 pull request 和主分支 push 自动运行。

### F. 前端工程规范

- [x] 增加 ESLint legacy 配置（与当前 ESLint 8 匹配）。
- [x] 将 `lint` 改为只读，将自动修复拆为 `lint:fix`。
- [x] 对历史告警设定可逐步收紧的规则，不在 Phase 0 大规模格式化旧代码。

## 4. 完成定义（Definition of Done）

Phase 0 只有同时满足以下条件才算完成：

1. 干净环境可以按文档安装最小依赖。
2. 新数据库可从零迁移，且模型无迁移漂移。
3. 后端 check 与选定核心测试通过。
4. 前端 lint 不修改代码且生产构建成功。
5. CI 能复现以上检查。
6. 仓库不再跟踪环境备份或示例之外的凭据。
7. 根目录启动说明与实际文件一致。

## 5. Phase 0 后的开发顺序

1. 抽离 API 执行引擎与运行上下文。
2. 增加提取器、断言器、钩子以及敏感数据脱敏。
3. 将套件执行迁移到 Celery worker。
4. 增加 OpenAPI 导入、快照、差异与影响分析。
5. 增加发布质量门禁及 CI 状态回传。

