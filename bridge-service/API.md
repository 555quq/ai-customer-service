# Bridge Service API 文档

## 概述

Bridge Service 是企业级 AI 客服系统的桥接服务，连接 Chatwoot 客服工作台和 Dify AI 引擎。

**技术栈**: FastAPI + Python 3.11  
**基础路径**: `http://localhost:8000`

---

## 端点列表

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST | `/webhook/chatwoot` | 接收 Chatwoot Webhook 事件 | 无 |
| POST | `/api/chat` | 直接聊天接口（测试用） | 无 |
| GET | `/health` | 健康检查 | 无 |
| GET | `/metrics` | Prometheus 监控指标 | 无 |
| GET | `/` | 服务信息 | 无 |

---

## 1. POST /webhook/chatwoot

接收 Chatwoot 的 Webhook 事件（用户消息），进行意图识别后调用 Dify AI 生成回复，根据置信度决定是否转人工。

### 请求体示例

```json
{
  "event": "message_created",
  "id": 12345,
  "content": "我想查询订单状态",
  "conversation": {
    "id": 100,
    "status": "open",
    "inbox_id": 1
  },
  "sender": {
    "id": 200,
    "name": "张三",
    "email": "zhangsan@example.com"
  },
  "message_type": "incoming",
  "created_at": 1717920000
}
```

### 响应体示例

**成功响应（200）**

```json
{
  "status": "success",
  "conversation_id": 100,
  "message_id": 12345,
  "action": "ai_replied",
  "intent": "order_query",
  "confidence": 0.95,
  "response_time_ms": 234
}
```

**转人工响应（200）**

```json
{
  "status": "success",
  "conversation_id": 100,
  "message_id": 12345,
  "action": "transferred_to_human",
  "intent": "complaint",
  "confidence": 0.45,
  "reason": "低置信度需要人工处理",
  "response_time_ms": 156
}
```

### 错误响应

**400 Bad Request**

```json
{
  "detail": "无效的 Webhook 数据格式"
}
```

**500 Internal Server Error**

```json
{
  "detail": "Dify API 调用失败"
}
```

---

## 2. POST /api/chat

直接聊天接口，用于测试 AI 回复功能，不依赖 Chatwoot。

### 请求体示例

```json
{
  "message": "你好，请问营业时间是？",
  "conversation_id": "test_conv_001",
  "user_id": "test_user_123"
}
```

### 响应体示例

**成功响应（200）**

```json
{
  "reply": "您好！我们的营业时间是周一至周五 9:00-18:00，周末 10:00-17:00。",
  "intent": "business_hours",
  "confidence": 0.92,
  "conversation_id": "test_conv_001",
  "response_time_ms": 189
}
```

### 错误响应

**400 Bad Request**

```json
{
  "detail": "消息内容不能为空"
}
```

**500 Internal Server Error**

```json
{
  "detail": "AI 服务暂时不可用"
}
```

---

## 3. GET /health

健康检查端点，用于监控服务状态和依赖服务连通性。

### 请求

无请求体

### 响应体示例

**健康状态（200）**

```json
{
  "status": "healthy",
  "service": "bridge-service",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "dependencies": {
    "dify": "ok",
    "chatwoot": "ok"
  }
}
```

**部分异常（503）**

```json
{
  "status": "degraded",
  "service": "bridge-service",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "dependencies": {
    "dify": "error",
    "chatwoot": "ok"
  }
}
```

---

## 4. GET /metrics

暴露 Prometheus 格式的监控指标。

### 请求

无请求体

### 响应体示例

```
# HELP bridge_requests_total 总请求数
# TYPE bridge_requests_total counter
bridge_requests_total{endpoint="/webhook/chatwoot",status="success"} 1523.0
bridge_requests_total{endpoint="/webhook/chatwoot",status="error"} 12.0

# HELP bridge_response_time_seconds 响应时间（秒）
# TYPE bridge_response_time_seconds histogram
bridge_response_time_seconds_bucket{le="0.1"} 234.0
bridge_response_time_seconds_bucket{le="0.5"} 1456.0
bridge_response_time_seconds_bucket{le="1.0"} 1523.0

# HELP bridge_ai_confidence AI 置信度
# TYPE bridge_ai_confidence gauge
bridge_ai_confidence{intent="order_query"} 0.95

# HELP bridge_transfer_to_human_total 转人工总数
# TYPE bridge_transfer_to_human_total counter
bridge_transfer_to_human_total 45.0
```

---

## 5. GET /

服务信息端点，返回服务基本信息。

### 请求

无请求体

### 响应体示例

**成功响应（200）**

```json
{
  "service": "Bridge Service",
  "version": "1.0.0",
  "description": "企业级 AI 客服桥接服务",
  "tech_stack": "FastAPI + Python 3.11",
  "endpoints": {
    "webhook": "/webhook/chatwoot",
    "chat": "/api/chat",
    "health": "/health",
    "metrics": "/metrics"
  }
}
```

---

## 错误码说明

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误或数据格式不正确 |
| 500 | 服务内部错误（如 Dify API 调用失败） |
| 503 | 服务降级或依赖服务不可用 |

---

## 意图识别类型

Bridge Service 通过 IntentAnalyzer 识别以下意图类型：

- `order_query` - 订单查询
- `refund_request` - 退款请求
- `complaint` - 投诉
- `product_inquiry` - 产品咨询
- `business_hours` - 营业时间
- `general` - 一般问题

---

## 转人工策略

当满足以下条件时，系统自动转人工：

1. AI 置信度 < 0.5（可配置）
2. 意图为 `complaint`（投诉）
3. 用户明确要求人工客服
4. 连续 3 次 AI 无法回答

---

## 部署说明

启动服务：

```bash
cd /Users/项目/ai客服/bridge-service
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

配置环境变量（`.env`）：

```
DIFY_API_KEY=your_dify_api_key
DIFY_API_URL=https://api.dify.ai/v1
CHATWOOT_API_URL=https://your-chatwoot.com/api/v1
CHATWOOT_API_KEY=your_chatwoot_api_key
CONFIDENCE_THRESHOLD=0.5
```

---

## 更新日志

- **v1.0.0** (2026-06-10): 初始版本，实现核心桥接功能
