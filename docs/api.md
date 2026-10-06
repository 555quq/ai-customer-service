# API 概览

本文档只列出稳定的功能边界。运行 Bridge 后可在 `/docs` 查看当前 OpenAPI 文档。

| 范围 | 路径 | 鉴权 |
|---|---|---|
| 健康 | `GET /health` | 无（仅返回受控状态） |
| 登录 | `/api/auth/*` | 用户名/密码、Refresh Cookie |
| Widget | `/api/widget/config`, `/api/widget/session` | 站点 Token/会话 Token |
| 对话 | `/api/chat`, `/api/chat/handoff` | Widget 能力 Token |
| 客服端 | `/api/agent/*` | Agent 或 Admin JWT |
| 管理端 | `/api/config/*`, `/api/knowledge/*`, `/api/admin/*` | Admin JWT |
| Webhook | `/webhook/chatwoot` | Adapter 签名与幂等控制 |
| WebSocket | `/ws/agent`, `/ws/widget` | 对应角色 Token |

应用集成时不要依赖未记录的内部字段。不得将 Admin JWT、模型 Key 或 Chatwoot Token 发给 Widget。
