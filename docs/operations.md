# 运维指南

## 日常检查

```powershell
./scripts/doctor.ps1
docker compose ps
docker compose logs --tail 200 bridge webhook-gateway webhook-worker
```

Bridge 健康检查为 `/health`，Prometheus 指标由内部监控网络采集。HTTP 200 不代表所有依赖健康，还应检查健康响应中的依赖状态。

## 备份、升级与回滚

```powershell
./scripts/backup.ps1
./scripts/update.ps1
./scripts/doctor.ps1
```

升级失败时使用 `scripts/rollback.ps1`；需要恢复数据时使用 `scripts/restore.ps1`。恢复会改写运行数据，必须先在隔离环境演练并验证备份完整性。

## 发布检查

```powershell
./scripts/release-check.ps1 -Quick
```

生产上线还需要真实模型、Chatwoot、Webhook、转人工、知识检索、备份恢复和公网边界验收。
