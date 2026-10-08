# cheapersafer.si 独立 Google Cloud 部署

本部署使用独立的 Google Cloud 项目，不读取或迁移原 RS 数据库、用户、模型渠道及密钥。应用仍基于 new-api / QuantumNous，保留上游版权及许可证。

| 资源 | 新项目配置 |
| --- | --- |
| Google Cloud 项目 | `cheapersafer-si-20261008` |
| 区域 | `europe-west1` |
| Cloud Run | `cheapersafer`，1 vCPU / 1 GiB，最多 1 实例，最少 0 |
| Cloud SQL | `cheapersafer-pg`，PostgreSQL 16，`db-f1-micro`，10 GB SSD |
| 数据库 / 用户 | `cheapersafer_api` / `cheapersafer_app` |
| Artifact Registry | `cheapersafer` |
| 源码暂存桶 | `cheapersafer-si-20261008-build-source` |
| 运行 / 构建账号 | `cheapersafer-runtime` / `cheapersafer-builder` |
| 密钥 | `cheapersafer-db-password`、`cheapersafer-database-dsn`、`cheapersafer-session-secret`、`cheapersafer-admin-login` |

项目使用当前账号的结算账号，但资源权限、数据库和费用记录独立。项目级每月 USD 200 预算用于告警，并非硬性限额。Cloud SQL 会持续计费。

## 首次部署

使用已经登录的 Google Cloud CLI。所有目标参数由 `cheapersafer.py` 固定，避免误操作原 RS 项目。源码构建使用干净的 Git HEAD archive，不携带本机配置和忽略文件。

```sh
python3 -m unittest discover -s deploy/google-cloud -p 'test_*.py'
python3 deploy/google-cloud/cheapersafer.py plan
python3 deploy/google-cloud/cheapersafer.py inspect
python3 deploy/google-cloud/cheapersafer.py budget
python3 deploy/google-cloud/cheapersafer.py provision
python3 deploy/google-cloud/cheapersafer.py build
python3 deploy/google-cloud/cheapersafer.py deploy --image 'BUILD_RETURNED_IMAGE_DIGEST'
python3 deploy/google-cloud/cheapersafer.py bootstrap
python3 deploy/google-cloud/cheapersafer.py publish
python3 deploy/google-cloud/cheapersafer.py verify
```

`deploy` 在初始化阶段启用 Google IAM 访问保护；`bootstrap` 初始化独立管理员 `csadmin`，关闭公开注册，并保存品牌、Logo 和实际 HTTPS 服务地址；`publish` 在检查应用鉴权后开放首页访问。管理员密码保存在新项目的 `cheapersafer-admin-login` Secret 中，不要提交到仓库或粘贴到聊天。

Cloud Run 默认 HTTPS URL 可独立访问。`cheapersafer.si` 自定义域名需要域名所有权验证与 DNS 记录。不要在域名尚未接通时把 `ServerAddress` 或 Cookie Origin 指向该域名。

## 后续更新

继续使用 `cheapersafer.py` 明确的目标参数。原有 `release.py` 和默认 `deploy.py` 仍服务于 RS 项目，不能用于 cheapersafer。

完整功能验收脚本也必须带新项目参数：

```sh
python3 deploy/google-cloud/acceptance.py \
  --project cheapersafer-si-20261008 --region europe-west1 \
  --service cheapersafer --sql-instance cheapersafer-pg --repository cheapersafer
```

该命令创建独立内部测试账号及临时 API Key，不配置真实模型上游。首次部署是低配置功能测试环境；用户数据、余额、渠道及模型价格需要在新项目后台单独配置。
