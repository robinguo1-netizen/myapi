# RS API Google Cloud 测试版准备说明

本文只描述部署准备，不会创建云资源、推送代码或镜像、触发 Cloud Build、修改 IAM 或公开服务。

## 已知目标

- Google Cloud 项目：`project-0338f2b7-06cf-4c5a-989`
- Cloud Run 服务：`superapi`
- 区域：`europe-west1`
- 当前 Cloud Build 触发器连接公开但为空的 GitHub 仓库 `robinguo1-netizen/myapi`，分支规则为 `^main$`。
- 当前触发器配置使用 buildpacks，不使用本仓库 Dockerfile。向 `main` 推送可能立即触发构建和部署，因此在仓库公开性、费用和发布策略确认前不得推送。

## 推荐部署形态

1. 使用根目录 `Dockerfile` 构建当前源码和 RS 前端。镜像监听 Cloud Run 注入的 `PORT`；应用现有实现已经读取该变量。
2. 使用 Cloud SQL for PostgreSQL 保存主数据和日志。测试版也必须启用持久化，不使用容器文件系统或 SQLite。
3. 多实例、较高并发或需要共享缓存时使用 Memorystore for Redis。无 Redis 的低流量试运营必须限制为最大 1 个实例；扩容前必须补齐并验证共享缓存、分布式限流和跨实例状态一致性。
4. `SESSION_SECRET`、数据库密码和 Redis 密码放入 Secret Manager，以运行时引用方式注入；不要写入仓库、镜像层、Cloud Build substitution 或普通环境变量文件。
5. 仅通过 Cloud Run HTTPS 域名访问，设置 `SESSION_COOKIE_SECURE=true`，并将最终精确 HTTPS Origin 写入 `SESSION_COOKIE_TRUSTED_URL`。
6. Cloud Run 请求超时应大于应用 `STREAMING_TIMEOUT`。建议测试版 Cloud Run 请求超时 300 秒、应用流式无响应超时 240 秒；这两个值只管理请求生命周期，不延长实例关机窗口。Cloud Run 发送 `SIGTERM` 后约 10 秒会强制终止实例，因此应用 `SHUTDOWN_TIMEOUT_SECONDS` 建议设置为 8 秒。
7. Cloud SQL 与 Redis 使用私网连接或受控连接器；不要为数据库、Redis 开放公共入站端口。

## Docker 与端口

现有生产 `Dockerfile` 会先构建 React 前端，再构建 Go 二进制，最终镜像入口为 `/new-api`。Cloud Run 会注入 `PORT`，无需硬编码 `8080`。本地完整联调使用同一个 Dockerfile，避免旧官方镜像与当前源码不一致。

当前 buildpacks 触发器不会自动采用 Dockerfile。后续需在以下两种方案中确认一种：

- 将触发器改为显式 Dockerfile 构建、推送 Artifact Registry 并部署 Cloud Run；或
- 暂停/隔离现有自动部署触发器，先由受控发布流程构建同一 Dockerfile，再人工批准部署。

在确认前不要向已连接仓库的 `main` 推送。

## Secret Manager 参数

最低必需：

- `RS_DATABASE_DSN` → `SQL_DSN`
- `RS_SESSION_SECRET` → `SESSION_SECRET`

使用 Redis 时再增加：

- `RS_REDIS_DSN` → `REDIS_CONN_STRING`

如果后续接入真实模型供应商、支付或邮件服务，每个供应商密钥应使用独立 Secret，并按最小权限绑定到 Cloud Run 运行服务账号。

## PostgreSQL 持久化与连接

- 使用独立测试数据库和最小权限数据库用户。
- 启用自动备份和时间点恢复；迁移前创建按需备份。
- 初始连接池建议 `SQL_MAX_IDLE_CONNS=10`、`SQL_MAX_OPEN_CONNS=30`，再根据 Cloud Run 最大实例数和 Cloud SQL 总连接上限调整。
- 计算约束：`最大实例数 × 每实例 SQL_MAX_OPEN_CONNS` 必须明显低于数据库连接上限，并为运维和迁移保留余量。
- DSN 使用 TLS，例如 `sslmode=require`；生产验收应进一步校验证书策略。

## 会话、限流与流式响应

- HTTPS 下必须启用 Secure Cookie 和精确 Origin 校验。
- 明确 Cloud Run 反向代理地址范围后再设置 `TRUSTED_PROXIES`，不要长期依赖宽泛默认值。
- 应用限流只是一层保护；公网测试版还应设置 Cloud Armor/API Gateway 或等效边界策略，并为登录、注册、密钥和转发接口设置告警。
- 保持 SSE/流式响应链路不启用会缓冲整个响应的代理设置。
- Cloud Run 请求超时、应用 `RELAY_TIMEOUT`、流式无响应超时 `STREAMING_TIMEOUT` 与客户端超时需要成组配置，但均不能保证请求在实例收到 `SIGTERM` 后继续运行。关机清理必须在 Cloud Run 约 10 秒的窗口内结束。
- 低流量、request-based CPU、scale-to-zero 的初始配置使用 `BATCH_UPDATE_ENABLED=false`，避免把扣费正确性依赖于闲置期内存定时 flush。启用批量扣费前必须单独验证实例冻结、终止和重试场景。
- 应用存在后台同步和定时任务；使用 request-based CPU 时必须验证这些任务在无请求期间的行为。若任务必须持续运行，应评估 instance-based CPU、最小实例或拆分为专用作业，而不是默认假定 scale-to-zero 下仍会执行。

## 待用户确认的最低规格

在创建任何收费资源前需要确认：

1. 客户主要地域和可接受延迟；当前 `europe-west1` 是否继续使用。
2. 云月预算上限以及是否允许 Cloud SQL 高可用、自动备份和 Memorystore。
3. GitHub 仓库是否可以继续公开；若不能，应先改为私有并复核 Cloud Build 连接权限。
4. Cloud Run 测试版是否保持仅授权访问，何时允许公网访问。
5. 初始建议：Cloud Run 1 vCPU / 1 GiB、最小实例 0、并发 20。未启用 Redis 时最大实例 1；启用并验证共享状态后才考虑最大实例 2。Cloud SQL 先选共享核心测试规格并启用持久化备份。具体 SKU 必须根据预算和地域确认后选择。
6. Redis 是首发即启用，还是仅在多实例/压测前启用。
7. 自定义域名、DNS、邮件、真实模型供应商和支付服务的责任方与启用时点。

## 上云前验收门槛

- 本地 PostgreSQL + Redis + 当前源码完整链路通过。
- 普通用户和管理员浏览器入口通过，无 504。
- 无效密钥、撤销密钥、余额不足均被拒绝。
- 非流式和流式请求、扣费、日志均通过本地可预测假上游验证。
- 镜像漏洞扫描、数据库备份恢复演练、Secret 轮换方案和回滚步骤完成。
- 明确仓库可见性、区域、预算和公网策略后，才允许创建或修改收费云资源。
