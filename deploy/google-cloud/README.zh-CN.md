# RS API Google Cloud 内部功能测试部署

RS API 基于 **new-api / QuantumNous** 开发；本流程构建现有 new-api Go 服务与 RS 前端，保留上游项目归属、许可证和版权信息。原生产 Dockerfile 的最终入口仍为 `/new-api`。

本目录提供显式、分阶段的部署流程。`deploy.py` 默认只输出计划；`provision`、`budget`、`build`、`deploy`、`bootstrap`、`publish` 会按名称创建资源或改变配置。必须先核对目标项目及现有资源，不能将此脚本直接用于其他已有业务环境。

## 已确认范围

- Google Cloud 项目：`project-0338f2b7-06cf-4c5a-989`，区域：`europe-west1`，Cloud Run 服务：`superapi`。
- 面向中国大陆以外地区的 2–3 名内部测试人员，公网 HTTPS 可访问，不设置 IAP、IP 白名单或额外网关。
- 保留应用自身的登录、角色权限和 API Key 验证；首次初始化完成后关闭公开注册。
- 月费用目标低于 USD 200。预算告警不是总费用硬上限；实例上限也不是精确的计费上限。数据库、存储、构建、出站流量和未来真实模型调用均需计入。
- 不改变现有 GitHub `^main$` buildpacks 自动触发器。应用代码位于 `rs-api-delivery-20260927` 分支；受控构建使用本仓库根 `Dockerfile`，不要向 `main` 推送来试图触发本流程。

公网地址即使未主动公开，也可能被扫描。这里不额外增加访问控制，但不能关闭应用鉴权或将数据库、管理密钥直接暴露。

## 最小测试规格

| 项目 | 配置 |
| --- | --- |
| Cloud Run | 1 vCPU、1 GiB；服务和修订版本均最大 1 实例、最小 0；并发 10 |
| CPU 与超时 | instance-based CPU（不节流），不启用 startup CPU boost；请求超时 300 秒，流式无响应超时 240 秒，关机清理 8 秒 |
| PostgreSQL | Cloud SQL PostgreSQL 16 Enterprise，`db-f1-micro`，单可用区，SSD 10 GB，无高可用、无自动扩盘 |
| 数据持久化 | 数据库 `rs_api`，用户 `rs_app`；每天备份，保留 3 份；测试阶段不启用 PITR |
| 数据库连接 | Cloud SQL Auth Proxy Unix socket；数据库启用公网 IP 供连接器使用，但强制连接器、没有公网授权网段 |
| 缓存 | 不部署 Redis，应用使用进程内缓存；`BATCH_UPDATE_ENABLED=false`，SQL 连接池 idle 2 / open 10 |
| 密钥 | Secret Manager 中保存密码、DSN、稳定会话密钥和初始管理员凭证；运行账号仅可读取 DSN、会话密钥 |
| 其他 | 不创建 VPC connector、负载均衡器、IAP 或 Cloud Armor |

低流量时 Cloud Run 可缩至零；Cloud SQL 即使无人使用仍持续收费。价格因区域、流量与计费规则而异，以 [Cloud Run 价格](https://cloud.google.com/run/pricing) 和 [Cloud SQL 价格](https://cloud.google.com/sql/pricing) 为准。脚本可创建 USD 200 的项目级月预算，在 USD 50 / 100 / 160 / 200 发送告警，发送到默认账单联系人；执行者必须有相应账单预算权限。

## 本机或 Cloud Shell 运行

需要 Python 3.9+、Git、tar 和支持相关标志的 Google Cloud CLI（本流程按 586.0.0 检查）。执行账号需已登录，且有操作目标项目资源、服务账号及预算的权限。不要将 OAuth token、密码或真实 DSN 复制到仓库或终端命令参数中。

```sh
python3 deploy/google-cloud/deploy.py plan
python3 deploy/google-cloud/deploy.py inspect
python3 -m unittest discover -s deploy/google-cloud -p 'test_*.py'
```

`inspect` 只报告所选安全配置字段和环境变量名称，不输出环境变量值、任意 annotations 或密钥。先核对已有 `superapi` 是否仅为未成功构建的占位服务；如发现真实业务，不要直接覆盖。

可通过 `--gcloud /绝对路径/gcloud` 或 `RS_GCLOUD` 指定 CLI。使用独立 `CLOUDSDK_CONFIG` 时，该目录必须被 Git 与 Docker 排除，权限建议为 `700`。

```sh
python3 deploy/google-cloud/deploy.py budget
python3 deploy/google-cloud/deploy.py provision
python3 deploy/google-cloud/deploy.py build
python3 deploy/google-cloud/deploy.py deploy --image 'europe-west1-docker.pkg.dev/PROJECT/rs-test/new-api@sha256:BUILD_RETURNED_DIGEST'
python3 deploy/google-cloud/deploy.py bootstrap
python3 deploy/google-cloud/deploy.py publish
python3 deploy/google-cloud/deploy.py verify
```

镜像参数必须替换成 `build` 实际输出的完整 digest。构建使用**确切的 Git HEAD archive**，不带本机未跟踪文件或忽略文件；未提交的应用更改会阻止构建。先审查并提交需要上线的应用变更。部署辅助目录的未提交修改可以用于运行流程，但不会悄悄混入应用源码镜像。

`provision` 使用专用构建和运行服务账号、Artifact Registry 仓库及源码暂存 bucket。源码对象 7 天过期；镜像目前不自动清理，反复构建后应按已确认的保留策略清理。脚本不会删除旧资源，也不会自动放宽不符合计划的现有 SQL 配置；部分完成后可检查再重跑对应阶段。

## 初始化与公开顺序

1. `deploy` 暂时启用 Cloud Run IAM 校验，移除公共 invoker 绑定，部署不可匿名访问的修订版本。
2. `bootstrap` 先确认匿名 `/api/setup` 被拒绝，再初始化 root 管理员，验证登录并将 `RegisterEnabled`、`PasswordRegisterEnabled` 都设为 false。
3. `publish` 再检查初始化、注册关闭和应用鉴权，随后关闭 Cloud Run invoker IAM 校验，成为用户要求的公网测试服务。
4. `verify` 不发送 Google 身份 token，以真正匿名访问方式复核公网状态、关闭注册和应用鉴权。

暂时的 IAM 保护只用于避免首次启动时他人抢先创建管理员，不是最终用户访问门槛。Google 身份验证使用 `X-Serverless-Authorization`，不会覆盖应用的 `Authorization` Bearer token。应用管理员凭证保存在 `${SERVICE}-admin-login` Secret 中；不要在聊天、日志或公开文档中粘贴。

若已有数据库或 root 用户，脚本不会覆盖其凭证。如果已存在的管理员密码与此 Secret 不匹配，必须人工核对，而不是重新初始化数据库。

## 应用配置与限制

- Cloud Run 自动注入 `PORT`；用 `--port=8080` 配置，不向环境变量手动写 `PORT`。
- PostgreSQL DSN 使用 `postgresql://` 协议和 `/cloudsql/PROJECT:REGION:INSTANCE` socket；`sslmode=disable` 只用于本地 socket，外层由 Cloud SQL Auth Proxy 提供认证与加密，不是开放不加密的远程数据库连接。参见 [Cloud Run 连接 PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run)。
- HTTPS Cookie 启用 Secure，并使用部署后精确 Origin。`SESSION_SECRET` 固定存放在 Secret Manager，不随修订版本随机变化。
- `TRUSTED_PROXIES=none` 忽略客户端伪造的转发 IP；初始测试人员可能共享限流计数。不要直接改成 `*` 或 `0.0.0.0/0`。
- 不启用 Redis 时，限流与部分聚合缓存属于单实例内存状态，会随重启重置。扩展到多实例前应验证共享缓存、分布式限流与会话/账务一致性。
- instance-based CPU 支持请求结束后的退款等后台操作，但实例缩零或终止仍会结束进程。现有退款 goroutine 没有完整关机排空保证；部署或切换修订版本前应停止测试请求，不运行依赖长后台任务的视频等流程。
- 核心余额与消费日志直接落 PostgreSQL；部分仪表盘聚合依赖定时刷新。`verify` 是部署冒烟测试，**不等于完整业务验收**。

## 上云后验收与维护

需另外验证实际登录、普通账号/API Key 管理、流式与非流式转发、成功扣费与日志一致、上游失败退款、无效/撤销密钥、余额不足，以及重启后的会话和数据持久化。没有真实模型供应商配置时，只能验收假上游或无上游路径，不能声称真实模型调用已通过。

最低规格无高可用、无 PITR，适合功能测试而非正式生产。生产前还需真实供应商费用保护、备份恢复演练、漏洞扫描、Secret 轮换和可验证回滚方案。回滚应用镜像前先确认数据库迁移兼容性；保留旧镜像不代表数据库可安全降级。暂停测试时仅缩零 Cloud Run 不会停止 Cloud SQL 的费用，删除或停用收费资源须另行确认数据保留要求。
