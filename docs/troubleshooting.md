# 故障排查

## Bridge 不健康

先运行 `pwsh ./scripts/doctor.ps1`，再查看 `docker compose logs --since 15m bridge`。若 `AI_PROVIDER=local`，重点检查 Qdrant、模型 API 和 embedding 初始化；系统不会静默切到 Dify。若为增强版，检查 `DIFY_API_URL`、应用 API Key 和 `dify-readiness` 输出。

## Chatwoot 收到消息但没有 AI 回复

先运行 `docker compose ps webhook-gateway webhook-worker bridge redis`。检查 Prometheus 中 `webhook_adapter_ingress_total`、`webhook_adapter_delivery_total`、`webhook_adapter_queue_depth`、`ai_customer_service_webhook_idempotency_total`、`ai_customer_service_webhooks_total`、`ai_customer_service_ai_requests_total` 和 `ai_customer_service_chatwoot_requests_total`。Webhook 返回 `accepted/processing_failed` 表示会话已保留但自动处理失败，应由客服接管。

若 Chatwoot 日志仍向 `host.docker.internal:8000` 或 `localhost:8000` 投递并产生 401/连接失败，通常是升级前的旧直连 Webhook。先确认名为 `AI Customer Service Webhook Adapter`（Chatwoot 3.11 可能不显示名称）的私网 Gateway Webhook 已成功工作，再由管理员删除旧直连记录；Setup 不会自动删除用户的其他 Webhook。

## Webhook 队列积压或出现死信

运行 `pwsh ./scripts/doctor.ps1`，再检查 `docker compose logs --since 15m webhook-worker bridge`。比较 `webhook_adapter_queue_wait_seconds` 与 `webhook_adapter_delivery_duration_seconds` 的 P95：两者同时升高通常是 Bridge、模型或 Chatwoot 变慢；仅排队升高时检查 Worker CPU、Redis 延迟、`WEBHOOK_ADAPTER_CONCURRENCY` 和缓冲占用。Bridge 暂停或返回 409/429/5xx 时 Worker 会自动重试；401/403/422 等永久错误会进入 `ai:webhook-adapter:dead-letter`。不要直接编辑 Redis Stream；先修复密钥、Bridge 配置或载荷兼容问题，再按受控运维流程重放。

## Webhook Worker 租约冲突或退出

P4-B 当前只支持一个 Worker 容器。第二个实例会报 `Another webhook worker is already active` 并退出，这是保护同会话顺序的预期行为。确认 Compose 中只有一个 `webhook-worker`，再用 Doctor 检查 `webhook-worker-lease` 与心跳。正常停止会立即释放租约；SIGKILL 或主机崩溃后等待默认 15 秒租约过期，再启动唯一的新 Worker 恢复 Pending。不要手工删除仍由健康 Worker 持有的租约。

Worker 在 Bridge 已完成但 ACK 前崩溃时，恢复过程可能重投同一事件；这是传输层至少一次语义。Bridge 依据稳定事件 ID 做幂等，重复请求不应产生第二次 AI/Chatwoot 业务效果。若观察到重复回复，应检查 `ai_customer_service_webhook_idempotency_total` 和 Redis 幂等存储，而不是关闭重试。

## 知识库导入失败

在管理端查看任务错误，然后检查 `ai_customer_service_knowledge_jobs_total{status="failed"}` 和 Qdrant 错误指标。相同内容再次上传会标记为 duplicate，不会重复索引。失败任务可重试，替换源文件时旧 ingestion 只在新 ingestion 成功后删除。

## Grafana 没有数据

确认 `docker compose ps prometheus grafana` 正常，访问 Bridge `/metrics/`，再检查 Grafana 数据源 URL 是否为 `http://prometheus:9090`。默认仪表盘按固定 UID 自动加载，手工修改不会持久化覆盖仓库版本。

## 升级失败

不要删除外部卷。执行 `scripts/rollback.ps1` 回到上一次已记录版本；如果数据迁移已改变数据，使用升级前备份运行 `scripts/restore.ps1`。详细步骤见 `docs/operations/a4-install-backup-upgrade-guide.md`。

## 收集诊断

```powershell
pwsh ./scripts/doctor.ps1 -Json
docker compose ps
docker compose logs --since 15m webhook-gateway webhook-worker bridge chatwoot-web chatwoot-worker qdrant
```

发送诊断前再次检查是否含客户消息、邮箱、手机号或密钥。

## Bridge 提示运行时配置无法解密

确认 `.env` 与 `bridge-service/.env` 中的 `CONFIG_ENCRYPTION_KEY` 与创建该配置或备份时的值一致。不要删除运行时配置或生成新密钥覆盖旧值；应从同一备份恢复环境文件和 `bridge-service/data`。错误密钥会让 Bridge 失败关闭，避免静默丢失客户配置。
