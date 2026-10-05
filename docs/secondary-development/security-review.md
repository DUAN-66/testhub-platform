# 复用平台安全检查与回归

个人负责对二次开发链路及依赖的用户、项目、环境管理进行风险定位、修复和回归验证，重点验证跨账号访问、恶意输入与失败时的阻断行为。

## 已修复的问题

| 风险 | 修复 | 验证 |
| --- | --- | --- |
| 普通用户修改、删除其他账户；目录回传联系方式 | 普通账户仅访问自己的详情，目录最小化，启用状态只读 | 跨账号 PATCH/DELETE、目录信息及只读字段回归 |
| 全局关闭 CSRF；API 登录创建浏览器会话 | 恢复会话 CSRF，API 登录只返回 JWT | 无 CSRF 会话请求拒绝；JWT 可用且不创建 session cookie |
| 后台主题移除防点击劫持中间件；静态入口缺少保护头 | 停用主题，保留后台 DENY；Nginx 配置 frame-ancestors、nosniff 等保护头 | 后台响应头、生产检查与容器前端实际响应 |
| GLOBAL 环境跨账户共享测试凭据 | 按创建者隔离，禁止借用他人全局环境，入队与 worker 执行前复核权限 | 列表、详情、旧套件执行、门禁规划、权限撤销和激活隔离 |
| 集合链接无权限项目、跨项目父节点或循环 | 校验项目权限、父节点归属，禁止迁移项目及循环 | 非法创建、修改回归 |
| 普通成员调整成员、删除项目 | 仅负责人允许对应操作 | 拒绝操作且数据保留 |
| 客户端修改执行历史 | 历史仅查询/删除，不接受创建或改写 | POST/PATCH 返回 405，原证据不变 |
| AI 配置回传明文 Key | 密钥只写；编辑留空保留原值 | 列表/详情不含密钥，更新保留原值 |
| HTTP 任意目标、重定向、环境代理及无限响应 | 精确主机白名单，禁重定向/环境代理，强制 TLS 校验，响应默认上限 2 MB；超时为 0–120 秒内有限正数 | 元数据地址、伪装主机、嵌入凭据、非法端口、Host 覆盖、超限响应；真实重定向不访问目标 |
| URL 内嵌凭据和敏感查询参数可能进入失败记录 | 记录 raw 与解码后的敏感值并脱敏，非法 URL 也处理 | 拒绝请求的真实历史快照、百分号/加号编码与异常回显 |
| 被测响应通过 `v-html` 渲染，可能执行 HTML | 响应组件使用 Vue 文本插值 | 编译实际组件，验证 img/script/svg 载荷被转义，JSON/中文正常展示 |
| 一次性登录码短且 GET/DELETE 非原子 | 完整随机 UUID，Redis GETDEL 原子消费 | 首次成功、重复失败，验证原子调用 |
| 危险默认值与可选模块直接开放 | 强密钥检查、关闭调试/注册/MCP，生产默认仅开放核心链路，Compose 绑定本机 | 占位密钥/通配符拒绝；可选 HTTP/WebSocket 入口拒绝 |

## 依赖与公开仓库

2026-10-05：前端首次官方 npm 审计报告 20 项已知漏洞，后端 API 依赖及传递依赖报告 241 项。升级 Django 5.2 LTS、DRF、HTTP/TLS、图像/PDF、ECharts、SheetJS 等后，两项审计均为 **0 项已知漏洞**。工具计数中一个软件包可能对应多个公告，不代表同样数量的独立可利用入口。

lockfile 保存完整性摘要，SheetJS 使用官方发行包。版本来源见 [Django 官方支持计划](https://www.djangoproject.com/download/)及 [SheetJS 官方安装说明](https://docs.sheetjs.com/docs/getting-started/installation/nodejs/)。可选浏览器、手机与 AI 扩展依赖不包含在 API 审计结论中。

公开快照未跟踪运行 `.env`、数据库、私钥和本机日志。扫描只输出路径，不输出匹配值。保留的 `financial_kb.json.bak` 是上游公开财报示例，不是运行配置备份。扫描覆盖当前跟踪文件的高置信凭据模式，不能替代全面秘密扫描或上游历史审计。

## 可复现验证

2026-10-05 本机验证：全仓 508 项通过、3 项环境条件跳过；其中后端安全回归 48 项通过，前端恶意响应测试 4 项通过。前端 lint 无错误（30 条既有警告），生产构建成功；迁移无漂移，依赖无冲突。契约引擎覆盖率 97%，门禁引擎 100%。

```bash
pip install -r requirements/dev.txt pip-audit==2.10.1
python scripts/verify_security.py
pytest apps/api_testing/tests/test_security.py
pip-audit -r requirements/api.txt
cd frontend
npm ci
npm audit --registry=https://registry.npmjs.org
npm run test:security
npm run lint
npm run build
```

CI backend 运行安全回归，frontend 运行恶意响应展示测试及 npm 审计，security 检查生产默认值、凭据模式及 API 依赖。integration、containers 验证真实 MySQL、Redis、独立 worker、实时日志与门禁，并使用 `verify_security_integration.py` 验证两次并发登录码兑换仅一次成功；使用隔离测试凭据，不保存 Token 或登录码。

生产安全检查无错误，保留 HSTS 子域和预加载两项提示，避免为未知子域强制 HTTPS。这两项由实际域名维护者决定，不通过屏蔽检查隐藏。

## 部署与剩余边界

1. `.env.example` 是生产安全模板，密钥须独立随机生成，例如 `python -c "import secrets; print(secrets.token_urlsafe(64))"`，真实值不得提交。演示使用 `backend.demo_settings` 或 `docker-compose.verify.yml`，演示凭据不得用于公网。
2. 生产设置 `API_TEST_ALLOWED_HOSTS=api.example.com`，不支持 `*`。主机白名单不是整个操作系统的网络沙箱；DNS、解析地址及所有端口仍须可信。worker 应处于独立网络，限制元数据/管理服务访问、CPU/内存及任务时长。
3. 生产要求 HTTPS。Compose 本机端口前需受控 TLS 网关；网关直接代理后端 API/WebSocket 并覆盖 `X-Forwarded-Proto` 后，才可设置 `TRUST_PROXY_SSL_HEADER=True`。容器 Nginx 是本地 HTTP 演示配置，不代表公网 HTTPS 部署已验证。
4. 核心模式是 HTTP/WebSocket 入口隔离，不是容器级代码隔离。可选模块的源码、后台模型和启动代码仍保留，直接客户端、脚本、上传与报告访问需另审。AI 密钥只写不等于数据库加密，须保护数据库和备份。
5. 分布式限流、登录暴力破解、外部通知、生产流量压测及完整渗透测试未验证。公网网关须限制登录频率并监测异常；验收结论限于隔离环境和列出的测试范围。

## 面试展示重点

可以讲清三条证据链：对象越权复现与拒绝测试；恶意响应和重定向的输入边界；依赖公告、升级、全量回归与 CI。展示自己负责的设计、修复和测试成果，同时明确上游来源和实际安全边界。
