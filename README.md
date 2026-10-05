# TestHub QualityGate — 接口回归与并发性能质量门禁

本仓库基于 [chenjigang4167/testhub_platform](https://github.com/chenjigang4167/testhub_platform) 二次开发，保留 GPL-3.0 许可证与上游归属。核心新增能力是 **OpenAPI 契约变更分析 → 受影响套件选择 → Celery 回归执行 → 可追溯质量门禁**。原有模块与本次独立开发范围在 [交付说明](docs/secondary-development/delivery.md) 中区分。

### 个人负责的核心开发与测试

在 TestHub 原有接口管理能力上，负责契约回归与质量门禁模块的设计、开发和验证，具体工作包括：

- 扩展并发性能门禁，采集真实 P50/P95/P99、错误率与成功 RPS，将性能执行绑定本次门禁；补充受限负载、独立目标授权、幂等投递、配置漂移检测与证据缺失阻断。
- 开发隔离商品与库存业务演示，定位并修复 N+1 查询（24 件商品业务查询 49→1），验证事务、MySQL 行锁、重复领取幂等和库存一致性。实测耗时与吞吐量由 CI 导出，详见 [性能门禁设计与复现](docs/secondary-development/performance-gate.md)。

- 对 OpenAPI 3.0 请求、响应、枚举、必填字段等做方向敏感的兼容性分析；无法证明兼容的变化标记 REVIEW 并阻断，拒绝远程引用与过量展开。
- 按 HTTP 方法和路径映射受影响套件，保留登录及变量提取前置步骤；未解析变量、缺少接口覆盖均显式阻断。
- 将门禁与本次执行 ID、契约摘要、用例配置指纹绑定；数据库唯一约束保证重复请求不重复投递。
- 独立 Celery 执行、状态机、任务取消、Redis WebSocket 实时日志、敏感字段脱敏。
- 可视化门禁页面、CI 命令行工具、持久化报告；通过率与 P95 预算参与决策，缺失或未完成证据不放行。
- GitHub Actions 验证单元测试、前端、真实 MySQL/Redis 联调与 Docker 完整链路，并保存验收证据。
- 对复用链路做安全回归与加固：对象权限、环境凭据隔离、CSRF、响应 XSS、HTTP 出站策略、原子登录码兑换、依赖升级与默认模块隔离。详见 [安全检查与验证](docs/secondary-development/security-review.md)。

**五分钟演示**：启动隔离环境后进入“接口测试 → 契约质量门禁”，选择 `QualityGate 演示` 项目。比较 baseline 与 compatible 应 PASS；比较 baseline 与 breaking 应 BLOCK，即使 HTTP 断言全部通过。详见 [运行、设计与限制](docs/secondary-development/quality-gate.md)。

### 验证结果

全仓回归 **538 项通过、3 项因环境条件跳过**；安全专项 **48 项后端回归、4 项前端恶意响应测试**通过。契约、功能/性能门禁与业务演示专项 **86 项通过**，契约分析引擎覆盖率 **97%**、门禁决策引擎 **100%**。前后端 API 依赖审计均为 **0 项已知漏洞**。[验收流水线](https://github.com/DUAN-66/testhub-platform/actions/workflows/quality.yml) 包含后端、前端、安全审计、真实 MySQL/Redis 联调及 Docker 验收；具体实测数据见对应提交的 `performance-verification.json` artifact；安全结果与范围见 [检查记录](docs/secondary-development/security-review.md)。

### 上游能力与扩展方向

复用 TestHub 的用户、项目、用例管理及原有 AI 辅助能力；AI 需求分析、用例生成与智能助手作为平台的辅助功能保留。契约兼容性和发布门禁由确定性规则及执行证据判定，便于复现和审计。

[![quality](https://github.com/DUAN-66/testhub-platform/actions/workflows/quality.yml/badge.svg)](https://github.com/DUAN-66/testhub-platform/actions/workflows/quality.yml)

<div align="center">

**接口持续测试与发布质量门禁**

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2_LTS-green.svg)](https://www.djangoproject.com/)
[![Vue](https://img.shields.io/badge/Vue-3.3-brightgreen.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-GPL_v3-blue.svg)](LICENSE)

</div>

## 📖 项目简介

接口测试二次开发的实现范围、启动步骤与验收证据见 [二次开发交付说明](docs/secondary-development/delivery.md)。

本项目以接口持续测试和发布质量决策为主线。以下介绍所复用的上游 TestHub 平台能力，包括用例管理与评审、API/UI/APP 测试、性能测试、数据工厂及 AI 辅助功能；个人负责的新增与重构范围见本文“个人负责的核心开发与测试”。

## ✨ 核心特性

### 🤖 AI 智能化
- **需求分析**: 上传需求文档（PDF/Word/TXT），AI 自动提取业务需求并生成测试用例
- **智能助手**: 集成 Dify AI 助手，提供测试咨询和问题解答
- **AI 智能模式**: 基于 Browser-use 的智能浏览器自动化，AI 理解页面并自动完成测试（支持文本/视觉两种模式）
- **多模型支持**: DeepSeek、通义千问、硅基流动、OpenAI、Anthropic、Google Gemini 等

### 📋 用例管理与评审
- 完整的用例生命周期管理：创建、编辑、版本控制、归档
- 多维度组织：项目、版本、标签分类；步骤化设计（前置条件 / 操作步骤 / 预期结果）
- 附件与团队协作评论
- 评审流程：多人评审、评审模板与检查清单、多层级评审意见、状态跟踪

### 🌐 API 测试
- 支持 HTTP / WebSocket 协议，树形集合组织，环境变量与变量替换
- 测试套件批量执行，支持断言与执行顺序配置
- 请求历史记录、定时任务（邮件 / Webhook 通知）、Allure 测试报告

### 🖥️ UI 自动化测试（Web）
- Selenium / Playwright 双引擎，多浏览器支持（Chrome / Firefox / Edge）
- 元素库（多种定位策略）+ 页面对象模式（POM）
- 可视化脚本编辑、测试套件批量执行、执行日志 / 截图 / 视频录制
- 定时任务：Cron 表达式、固定间隔、单次执行
- AI 智能模式：AI 理解页面结构自动完成测试任务

### 📱 APP 自动化测试（Android）
- 基于 Airtest 图像识别，支持本地模拟器与远程设备，设备锁定避免资源冲突
- 元素管理（图片 / 坐标 / 区域）与多分辨率适配
- 组件化编排 + UI Flow 流程编排，变量管理（global / local / outputs）
- Celery 异步执行 + Allure 报告，WebSocket 实时进度追踪

### 🚀 性能测试
- 基于 Locust 的压测任务管理与执行，性能指标统计与报告

### 🏭 数据工厂
- 50+ 实用工具：字符处理、编码转换、随机数据、加密解密、测试数据生成、JSON 处理、Crontab 表达式等
- 标签管理与使用记录，支持在 API 测试与 UI 测试中直接引用数据

### 🔐 安全与协作
- JWT 双 Token 机制：自动刷新续期、登出黑名单；一次性登录码原子兑换
- 多项目管理、成员角色权限控制、版本规划
- 统一通知：邮件 + 企业微信 / 钉钉 / 飞书 Webhook 机器人

## 🏗️ 技术架构

### 后端
- **框架**: Django 5.2 LTS + Django REST Framework
- **数据库**: MySQL 8.0+
- **认证**: JWT（rest_framework_simplejwt）+ Token 黑名单
- **自动化**: Selenium、Playwright、Airtest + OCR、Allure
- **异步与任务**: Celery、APScheduler、Channels + Daphne（WebSocket）
- **AI 集成**: browser-use、langchain-openai，多模型提供商
- **API 文档**: drf-spectacular（Swagger / ReDoc）

### 前端
- Vue 3 + Vite + Element Plus
- Pinia 状态管理、Vue Router、Axios
- ECharts 可视化、Monaco Editor、vue-i18n 国际化

在进行 Web、API 及自动化测试时，不同地区的网络环境可能带来不同的访问体验。IPWO住宅代理，支持多地区网络环境配置，可用于海外网站访问、区域测试及自动化测试场景。

<u>[IPWO](https://www.ipwo.net/?ref=githubplatform)</u>为 TestHub 用户提供更多测试环境选择，让跨地区测试更加灵活。覆盖全球195+地区动静态IP资源，支持免费测试入口，90折扣码：0204
![img.png](static_files/img.png)

## 📁 项目结构

```
testhub_platform/
├── apps/                           # Django 应用模块
│   ├── users/                      # 用户认证与管理
│   ├── projects/                   # 项目管理
│   ├── testcases/                  # 测试用例管理
│   ├── testsuites/                 # 测试套件
│   ├── executions/                 # 测试计划与执行
│   ├── reports/                    # 测试报告
│   ├── defects/                    # 缺陷管理
│   ├── reviews/                    # 用例评审
│   ├── versions/                   # 版本管理
│   ├── core/                       # 核心模块（管理命令、变量解析、通知配置）
│   ├── api_testing/                # API 测试
│   ├── ui_automation/              # UI 自动化测试（含 AI 智能模式）
│   ├── app_automation/             # APP 自动化测试
│   ├── perf_testing/               # 性能测试
│   ├── requirement_analysis/       # AI 需求分析
│   ├── assistant/                  # Dify 智能助手
│   ├── data_factory/               # 数据工厂
│   └── llm_judge/                  # LLM 评测
├── backend/                        # Django 项目配置（settings / urls / asgi）
├── frontend/                       # Vue 3 前端（src: views / api / stores / router）
├── media/                          # 媒体文件（上传文件、截图等）
├── logs/                           # 日志文件
├── allure/                         # Allure 报告工具
├── requirements.txt                # Python 依赖
└── manage.py                       # Django 管理脚本
```

## 🚀 快速开始

### 环境要求

- **Python**: 推荐 3.11–3.12
- **Node.js**: 18+（前端构建必需，生产环境可不安装）
- **MySQL**: 8.0+
- **Java**: 17+（可选，Allure 报告生成需要）
- **Redis**: 6.0+（可选，APP 自动化 WebSocket / Celery 需要）
- **浏览器驱动**: ChromeDriver / GeckoDriver（UI 自动化，也可通过管理命令自动下载）

### 后端部署

1. **克隆项目**
```bash
git clone https://github.com/DUAN-66/testhub-platform.git
cd testhub-platform
```

2. **创建虚拟环境并安装依赖**
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / Mac
source venv/bin/activate

# 默认：接口测试二开与开发验证
pip install -r requirements.txt

# 可选引擎依赖参见 requirements/，部署前须进行专项验证
# 完整回归测试收集所需依赖
# pip install -r requirements/regression.txt
```

3. **配置环境变量**
```bash
# 复制模板并按需修改数据库、Redis、邮箱等配置
cp .env.example .env
# 生成独立随机密钥，写入 .env 的 SECRET_KEY；不要提交真实值
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

模板默认为生产安全配置，须配好 HTTPS 入口与明确的接口目标白名单。只做本机演示可直接使用 [隔离演示步骤](docs/secondary-development/delivery.md)，无需复制生产模板；公网部署范围与代理配置见 [安全记录](docs/secondary-development/security-review.md)。

4. **初始化数据库**
```bash
# 创建数据库与最小权限业务账号（密码需与 .env 一致）
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS testhub CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER IF NOT EXISTS 'testhub'@'localhost' IDENTIFIED BY 'replace-with-a-strong-password'; GRANT ALL PRIVILEGES ON testhub.* TO 'testhub'@'localhost';"

# 执行仓库中已提交的迁移并创建超级用户
python manage.py migrate
python manage.py createsuperuser
```

5. **初始化模块数据（可选）**
```bash
# UI 自动化元素定位策略
python manage.py init_locator_strategies
# APP 自动化组件库
python manage.py load_component_pack
```

6. **启动服务**
```bash
# Django 开发服务器（仅 HTTP）
python manage.py runserver

# 如需 WebSocket（接口/APP 自动化实时进度），改用 Daphne 启动
daphne -b 127.0.0.1 -p 8000 backend.asgi:application

# 定时任务调度器（API / UI 定时任务，可选）
python manage.py run_all_scheduled_tasks

# Celery worker（接口套件异步执行必需，另开终端）
celery -A backend worker -l info
# Windows 本地演示使用 --pool=solo --concurrency=1
```

### 前端部署

```bash
cd frontend
npm ci
npm run dev        # 开发模式
npm run build      # 生产构建
```

### 访问应用

- **前端**: http://localhost:3000
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/api/docs/
- **Admin 后台**: http://localhost:8000/admin/

### Docker 部署（可选）

```bash
# 首次使用前在 .env 设置随机 SECRET_KEY、独立数据库密码与生产 HTTPS 配置
docker compose up -d --build
```

Compose 会启动 MySQL、Redis、Django/Daphne、Celery worker 与前端 Nginx。请勿使用示例密码部署到生产环境。早期版本曾跟踪环境备份文件，从旧版本升级时应主动轮换其中出现过的凭据。

## 🔧 配置说明

环境变量统一在 `.env` 中配置（参考 `.env.example`），主要包括：

- **数据库**: `DB_NAME`、`DB_USER`、`DB_PASSWORD`、`DB_HOST`、`DB_PORT`
- **Redis**: `REDIS_URL`（APP 自动化 WebSocket / Celery 需要）
- **AI 模型**: 在「统一配置中心」管理多家提供商的 API Key / Base URL / 模型参数，支持按角色配置（用例编写、用例评审、Browser Use），并提供连接测试
- **UI 自动化**: 执行引擎（Selenium / Playwright）、浏览器、有头 / 无头模式
- **通知**: 邮件（SMTP）与 Webhook 机器人（企业微信 / 钉钉 / 飞书）

## 📄 文档

更多使用说明见 [docs/docs-center](./docs/docs-center/)：

- **二开主线**：[Phase 0 整改清单](./docs/secondary-development/phase-0-remediation.md) / [目标架构](./docs/secondary-development/target-architecture.md) / [数据模型](./docs/secondary-development/data-model.md) / [API 协议](./docs/secondary-development/api-contract.md) / [统一接口执行引擎](./docs/secondary-development/api-execution-engine.md) / [Celery 异步执行与实时日志](./docs/secondary-development/async-execution.md)

- **[数据工厂使用说明](./docs/docs-center/数据工厂使用说明.md)** / **[快速开始](./docs/docs-center/数据工厂快速开始.md)** / **[功能说明](./docs/docs-center/数据工厂功能说明.md)** / **[API 接口文档](./docs/docs-center/数据工厂API接口文档.md)**
- **[UI 自动化测试执行说明](./docs/docs-center/UI自动化测试执行说明.md)** / **[UI 自动化测试用户使用手册](./docs/docs-center/UI%20自动化测试用户使用手册.md)**
- **[WebDriver 驱动管理优化说明](./docs/docs-center/WebDriver驱动管理优化说明.md)**
- **[用例评审管理功能说明](./docs/docs-center/用例评审管理功能说明.md)**
- **[I18N 国际化使用说明](./docs/docs-center/I18N国际化使用说明.md)**
- **[问题排查指南](./docs/docs-center/问题排查指南.md)**



## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request 来帮助改进项目！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📝 许可证

本项目采用 GPL 3.0 许可证 - 详见 [LICENSE](LICENSE) 文件

## 问题反馈

本项目的问题与建议请提交到 [GitHub Issues](https://github.com/DUAN-66/testhub-platform/issues)。

## 上游致谢

感谢上游 [TestHub](https://github.com/chenjigang4167/testhub_platform) 及原作者大刚提供的平台基础。本仓库的新增开发范围见“个人负责的核心开发与测试”，并继续遵循 GPL-3.0 许可证。
