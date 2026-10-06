# 安装指南

## 需求

- 4 核 CPU、8 GB 内存、20 GB 可用空间
- Docker Engine / Docker Desktop 和 Docker Compose v2
- PowerShell 7.2+
- 可用的 OpenAI 兼容模型 API

## 标准安装

```powershell
Copy-Item .env.example .env
./scripts/install.ps1
```

脚本会检查容量和端口，生成随机密钥，创建外部数据卷，构建应用并等待健康检查。不要直接使用 `.env.example` 中的 `REQUIRED_CHANGE_ME_*` 占位值启动生产环境。

安装完成后打开 `http://localhost:5175/setup`，完成管理员、客服、模型、Chatwoot 和 Widget 初始化。

## 生产入口

准备 Admin、Agent、Widget 和 Chatwoot 四个子域名，完成 `.env` 中的 DNS、ACME 邮箱和 Admin 白名单后执行：

```powershell
./scripts/install.ps1 -Production
./scripts/acceptance-ingress-local.ps1
```

真实 DNS、云防火墙、证书签发和白名单外访问必须在目标服务器上另行验收。
