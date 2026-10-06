# v1.0.0 发布验收清单

验收环境必须是全新或可销毁的独立服务器，禁止在现有客户数据上做破坏性恢复演练。

完整服务器验收按 [`A2 全新服务器生产验收手册`](../operations/a2-server-acceptance-runbook.md) 的 A2-0～A2-7 顺序执行。A0 本机验收与 A1 镜像构建不能替代 A2 签字。

> **发布硬门禁：** Stock Chatwoot 必须将真实事件投递到私有 Gateway，由 Worker 使用 HMAC v2 向 Bridge 转发。不得关闭鉴权、接受无签名请求、开放 Gateway 宿主机端口或用模拟请求替代。此项未通过时，结论最高只能是“有条件通过”，不得正式生产发布。

## 自动检查

```powershell
pwsh ./scripts/release-check.ps1
pwsh ./scripts/install.ps1
pwsh ./scripts/doctor.ps1
pwsh ./scripts/webhook-load-test.ps1
```

保留 `diagnostics/release-check-*.json`、`install-*.json` 和 `doctor-*.json`。

## U1 生产入口门禁

- [ ] 四个真实 DNS 子域名分别指向同一台验收服务器，且 `CADDY_IMAGE` 使用固定 SHA-256 摘要。
- [ ] `docker-compose.yml` 与 `docker-compose.production.yml` 合并后只有 Caddy 发布公网 `80/443`；其余宿主机端口均为回环绑定，Gateway/Worker 无宿主机端口。
- [ ] Caddy 配置通过 `caddy validate`，Admin/Chatwoot 白名单为空或解析失败时安装失败关闭。
- [ ] Admin/Chatwoot 白名单外访问返回 403，伪造 `X-Forwarded-For` 不能绕过；Agent 可正常登录并使用 WSS。
- [ ] Widget Host 仅能访问六组公开路由，其余管理、健康、指标和 Agent WebSocket 路径返回 404。
- [ ] 四个 HTTPS 入口证书有效，HTTP 只跳转 HTTPS，Caddy 重启后证书卷仍可用。
- [ ] `pwsh ./scripts/doctor.ps1 -Production` 与 `pwsh ./scripts/release-check.ps1` 无失败项。

本机 `.localhost` 入口通过只证明 Caddy、Compose 和路由边界可运行；真实 ACME、DNS、云防火墙、外部白名单和公网探测必须在 A2 独立服务器完成。

## 标准版真实流程

- [ ] Setup v2 向导只可初始化一次，同时保存 Admin/Agent Argon2id 哈希，模板密码和明文全部失效。
- [ ] 同一浏览器中 Admin 与 Agent 可同时登录并分别刷新；Admin 退出不影响 Agent。
- [ ] Admin 轮换 Agent 密码后旧 Refresh 会话无法续期，新密码可登录，响应不暴露密码或哈希。
- [ ] 从 Setup v1 升级时，旧共享 Cookie 失效后两端重新登录；Admin 已先在“登录安全”配置 Agent 强凭据。
- [ ] Widget 加载、会话令牌、普通问答和 WebSocket 回复正常。
- [ ] Setup 幂等创建/更新 `AI Customer Service Webhook Adapter`，只订阅 `message_created`；重试不会重复创建。
- [ ] Chatwoot 3.11 真实扁平 `message_created` 经 Gateway → Redis → Worker HMAC v2 → Bridge，走 `AI_PROVIDER=local` 并在同一会话产生 AI 回复。
- [ ] Gateway/Worker 无宿主机发布端口；生产拒绝 v1、过期时间戳、篡改事件 ID/正文和错误签名。
- [ ] 低置信度、关键词和连续未解决能转人工，客服回复同步到访客。
- [ ] 上传知识文件后任务完成、检索命中；重复上传不重复索引；失败任务可重试。
- [ ] 管理员与客服 RBAC、过期 token、错误 origin、错误 webhook 签名均被拒绝。
- [ ] Prometheus 有 AI/Chatwoot/Qdrant/Webhook 入口、队列、投递、死信、去重、转人工和知识任务指标，Grafana 默认仪表盘可用。
- [ ] P4-B 确定性门禁通过：持续 60 条/分钟、50 条突发在 5 秒内完成、同会话 20 条严格有序、重试不阻塞其他会话、最终队列归零。
- [ ] 使用 6 个专用 Chatwoot 会话显式运行 `webhook-real-ai-smoke.ps1 -ConfirmRealAiCost`；5 会话并发和同会话连续 3 条均无丢失、重复或乱序，并保存脱敏报告。

## 故障与恢复

- [ ] 停止 Qdrant，AI 降级且产生告警；恢复后检索恢复。
- [ ] 停止 Chatwoot，Webhook/发送错误可观测且会话不静默丢失。
- [ ] 停止 Bridge 后发送事件，确认 Stream 保留；恢复 Bridge 后 Worker 自动重试并清空。
- [ ] 停止 Worker 后发送事件，确认 Stream 保留；恢复 Worker 后自动消费并清空。
- [ ] 在队列有事件时重启 Redis，确认 AOF 恢复事件并最终投递成功。
- [ ] 模型 API 超时，重试与转人工路径符合预期。
- [ ] 创建备份，向系统写入可识别测试数据，再在可销毁环境执行 restore 并核对数据。
- [ ] 执行一次 update/rollback，确认镜像记录和数据不丢失。

## Dify 增强版

- [ ] 每客户独立 Dify `1.16.1` 已备份并健康。
- [ ] 使用 overlay 与 `--profile dify` 启动，readiness 成功。
- [ ] Bridge 明确为 `AI_PROVIDER=dify`，问答与错误指标 provider 标签正确。
- [ ] 移除 overlay 后标准版恢复 local，且不会访问 Dify。

## 签字

| 项目 | 内容 |
|---|---|
| 版本/Commit | |
| 环境 | |
| 验收时间 | |
| 验收人 | |
| 自动报告路径 | |
| 未通过项与处置 | |
| 结论 | 通过 / 有条件通过 / 不通过 |
