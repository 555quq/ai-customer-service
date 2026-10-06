# 贡献指南

## 开发环境

- Python 3.12
- Node.js 20.19.4
- pnpm 10.34.0
- PowerShell 7.2+
- Docker Compose v2

Fork 仓库后从 `main` 创建功能分支。提交专注于一个可审查的改动，不要同时夹带无关重构。

## 提交前检查

```powershell
Set-Location bridge-service
python -m pytest tests -q

Set-Location ../frontend
corepack pnpm install --frozen-lockfile
corepack pnpm test
corepack pnpm typecheck
corepack pnpm build

Set-Location ..
./scripts/release-check.ps1 -Quick
```

PR 必须说明问题、解决方案、验证命令和安全影响。不得提交 `.env`、Token、真实会话、客户文档、日志、备份或模型缓存。

修复安全漏洞时，请先按 [SECURITY.md](SECURITY.md) 私下联系维护者。
