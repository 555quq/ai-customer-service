# 配置指南

## 配置边界

`.env` 保存基础设施密钥和端口；Admin 初始化向导保存模型、Chatwoot、Widget 和业务规则。运行时敏感配置使用 `CONFIG_ENCRYPTION_KEY` 进行认证加密。

## 模型

标准版调用 OpenAI 兼容的 `/chat/completions` 接口。需要配置 API Base、模型名称和 API Key。Embedding 默认使用 FastEmbed 本地模型，知识向量存入 Qdrant。

## Chatwoot

需要 Chatwoot Base URL、Account ID、API Inbox ID 和 API Token。初始化向导会验证连接并配置受签名保护的 Webhook Adapter。

## Widget

配置站点名称、欢迎语、主题、位置、站点 Token 和允许来源。生产环境必须使用 HTTPS 公开 Base URL，且只允许客户网站的精确 Origin。

## Dify

Dify 不是标准版强依赖。需要时使用 `docker-compose.dify.yml` overlay 并配置独立客户 Dify 实例。
