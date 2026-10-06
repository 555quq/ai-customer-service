# AI Customer Service

一套 Docker-first、单客户自托管的 AI 智能客服系统，将网页 Widget、企业知识库、大模型和 Chatwoot 人工客服连接起来。

## 主要功能

- 可嵌入普通网页的独立 `widget.js`
- OpenAI 兼容模型接口与可选 Dify 增强模式
- FastEmbed + Qdrant 知识库检索
- Chatwoot 人工转接、会话分配和消息同步
- Admin 管理端、Agent 客服端和访客 Widget
- JWT/RBAC、配置加密、Webhook 签名和限流
- Prometheus、Grafana 及告警规则
- 安装、诊断、备份、恢复、升级和回滚脚本

## 架构

```text
客户网站 / Widget
        │
        ▼
Bridge Service (FastAPI)
   │        │        │
   ▼        ▼        ▼
模型 API   Qdrant   Chatwoot
              │       │
            Redis   PostgreSQL
```

## 快速开始

需要 Docker Engine / Docker Desktop、Docker Compose v2 和 PowerShell 7.2+。建议至少 4 核 CPU、8 GB 内存和 20 GB 可用空间。

```powershell
Copy-Item .env.example .env
./scripts/install.ps1
```

安装脚本会为数据库、Redis、JWT、Webhook 和运行时配置生成随机密钥。完成后访问 `http://localhost:5175/setup` 设置管理员、客服、模型和 Chatwoot 配置。

详细步骤见 [安装指南](docs/installation.md) 和 [配置指南](docs/configuration.md)。

## 嵌入 Widget

在 Admin 中完成初始化后复制 Widget 代码，添加到网页 `</body>` 前：

```html
<script
  src="https://widget.example.com/assets/widget.js"
  data-api-base="https://widget.example.com"
  data-site-token="由管理端生成的站点令牌"
  data-theme="light"
  data-locale="zh-CN">
</script>
```

见 [Widget 集成](docs/widget-integration.md)。模型 Key、Chatwoot Token 和管理员凭据绝不应出现在浏览器代码中。

## 验证

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

## 生产安全

**不要把开发端口直接暴露到公网。** 上线前必须使用 HTTPS、强随机密钥、精确 CORS/来源白名单、Admin/Chatwoot 访问限制，并完成备份恢复演练。请阅读 [安全加固](docs/security-hardening.md) 和 [运维指南](docs/operations.md)。

## 已知限制

- 当前是单客户、单实例交付，不是统一 SaaS 多租户平台。
- 当前只有一个可配置 Agent 身份，尚无完整多客服账号体系。
- 不内置订单、ERP 或商城查询集成。
- Dify 和标准版 Qdrant 的知识数据不会自动互相迁移。
- 部署者需自行准备服务器、域名、模型 API 和 Chatwoot 配置。

## 文档

- [安装](docs/installation.md)
- [配置](docs/configuration.md)
- [Widget 集成](docs/widget-integration.md)
- [运维](docs/operations.md)
- [API](docs/api.md)
- [安全加固](docs/security-hardening.md)
- [故障排查](docs/troubleshooting.md)
- [v1.0.0 发布说明](docs/release/v1.0.0.md)

## 贡献与安全报告

贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全漏洞请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中提交密钥或客户数据。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
