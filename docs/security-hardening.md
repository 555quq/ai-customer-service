# 生产安全加固

上线前必须完成以下项目：

- 运行 `scripts/install.ps1` 生成随机 PostgreSQL、Redis、JWT、Setup Token、运行时配置加密和 Grafana 密钥，不使用模板值。
- 运行时配置中的模型、Chatwoot、Widget 和密码字段使用 `CONFIG_ENCRYPTION_KEY` 认证加密；该密钥只保存在环境配置和受控备份中，不得提交 Git。轮换密钥前必须先完成受控解密/重加密迁移，不能直接替换环境变量。
- 管理端、客服端、Bridge、Chatwoot 全部放在 TLS 反向代理后；设置 `AUTH_COOKIE_SECURE=true`。
- `AUTH_ALLOWED_ORIGINS` 只列出实际管理端和客服端域名，禁止 `*`。
- 使用安装器分别生成 `CHATWOOT_ADAPTER_INGRESS_TOKEN` 和 `CHATWOOT_WEBHOOK_SECRET`，两者不得复用；前者仅由 Chatwoot、Gateway 和 Setup 使用，后者仅由 Worker 与 Bridge 使用。
- `webhook-gateway` 和 `webhook-worker` 只暴露 Compose 私网端口，不得添加宿主机 `ports`。生产 Bridge 保持 `WEBHOOK_ALLOW_LEGACY_V1=false`。
- Worker 使用 HMAC v2 对 `timestamp + "\n" + event_id + "\n" + raw_body` 签名；Bridge 在解析 JSON 前验证版本、时间窗口、事件 ID 和原始正文，避免篡改与重放。
- Redis 必须保持 `appendonly yes` 与 `appendfsync always`。Bridge 在 Redis 幂等存储不可用时返回 503，不得绕过处理锁继续执行业务。
- 当前只允许一个 `webhook-worker`；Redis 比较令牌租约用于阻止误启动第二实例。不得通过删除租约、复制 Worker 服务或设置 Compose 副本数来绕过该限制。
- Worker 默认并发 8，并以每会话 FIFO 保证顺序；缓冲上限 256。调整并发前必须运行确定性负载门禁，并保持 `prefetch >= concurrency`、`buffer_limit >= prefetch`、租约 TTL 大于两倍续租间隔。
- PostgreSQL、Redis、Qdrant、Prometheus、Grafana 端口只对服务器本机或运维网开放。
- `.env`、`bridge-service/.env`、备份包和诊断报告按敏感数据管理，不提交 Git。
- 为备份目录配置访问控制和离线副本；至少每季度在隔离环境验证一次恢复。
- 管理员与客服账号使用独立强密码，运行时只保存 Argon2id 哈希；不在 `.env` 中保留明文默认密码。
- Admin 与 Agent 必须使用独立的 HttpOnly Refresh Cookie。任一角色退出只撤销自身会话，不得共享 Cookie 或端口间覆盖会话。
- 离职、角变化或凭据疑似泄漏时，立即在 Admin“登录安全”中轮换 Agent 凭据并确认旧 Refresh 会话已撤销。
- Dify 增强版必须每客户独立部署、独立密钥、独立备份。

上线验收时运行：

```powershell
pwsh ./scripts/release-check.ps1
pwsh ./scripts/doctor.ps1
pwsh ./scripts/webhook-load-test.ps1
```

`doctor.ps1` 输出会做常见凭证脱敏，但诊断报告仍可能包含主机与服务拓扑，只应提供给授权运维人员。

## 生产 HTTPS 入口（U1）

生产入口使用 `docker-compose.yml` 加 `docker-compose.production.yml`。Caddy 是唯一发布宿主机 `80/443` 的服务；PostgreSQL、Redis、Chatwoot、Qdrant、Bridge、Admin、Agent、Prometheus 和 Grafana 默认绑定 `127.0.0.1`，Gateway/Worker 不发布宿主机端口。

正式部署前必须填写四个不同的真实子域名、ACME 邮箱、`ADMIN_ALLOWED_CIDRS`、`WIDGET_PUBLIC_BASE_URL` 和带 SHA-256 摘要的 `CADDY_IMAGE`。Admin 与 Chatwoot 在 Caddy 层使用同一份白名单，空白或全网 CIDR 会失败关闭；不要通过设置 `HOST_BIND_ADDRESS=0.0.0.0` 绕过入口。

Widget Host 只允许资源、配置、会话、聊天、handoff 和 `/ws/widget` 六组精确路由。生产缺少公开 Widget Origin 时，snippet 返回 `WIDGET_PUBLIC_URL_NOT_CONFIGURED`，不会回退到 Admin Host、容器地址或公网自报的转发头。生产安装与诊断分别使用：

```powershell
pwsh ./scripts/install.ps1 -Production -AgentPassword (Read-Host 'Agent password' -AsSecureString)
pwsh ./scripts/doctor.ps1 -Production
pwsh ./scripts/release-check.ps1
```

没有真实 DNS 和服务器时，可使用 `pwsh ./scripts/acceptance-ingress-local.ps1 -Start`、`.localhost` 和 Caddy 本地 CA 验证 HTTPS、路由及回环端口；真实 ACME、云防火墙、公网白名单、备份恢复和回滚仍需 A2 独立服务器签字。脚本默认只做配置校验，只有显式传入 `-Start` 才会启动本地生产 Overlay；不传 `-KeepStack` 时会在探测后停止容器但保留数据卷。
