# Bridge Service

企业级 AI 客服系统的桥接服务，连接 Chatwoot 客服工作台和 Dify AI 引擎。

## 技术栈

- **框架**: FastAPI + Python 3.11+
- **异步 HTTP**: httpx
- **配置管理**: Pydantic Settings
- **日志**: Loguru
- **监控**: Prometheus

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，填入实际配置
nano .env
```

**必填配置**:
- `CHATWOOT_API_TOKEN`: Chatwoot API 访问令牌
- `DIFY_API_KEY`: Dify AI API 密钥

### 3. 启动服务

```bash
# 开发模式（自动重载）
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 4. 验证部署

```bash
# 健康检查
curl http://localhost:8000/health

# 查看 API 文档
open http://localhost:8000/docs
```

## 项目结构

```
bridge-service/
├── src/
│   ├── main.py              # 应用入口
│   ├── config.py            # 配置管理
│   ├── models/
│   │   └── webhook.py       # Webhook 数据模型
│   ├── services/
│   │   ├── chatwoot.py      # Chatwoot API 客户端
│   │   ├── dify.py          # Dify AI 客户端
│   │   └── intent.py        # 意图识别
│   └── utils/
│       ├── cache.py         # 缓存工具
│       └── metrics.py       # 监控指标
├── tests/
│   ├── conftest.py          # Pytest 配置
│   └── test_integration.py # 集成测试
├── requirements.txt         # Python 依赖
├── .env.example            # 环境变量模板
├── pytest.ini              # Pytest 配置
├── API.md                  # API 文档
└── README.md               # 本文件
```

## API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/webhook/chatwoot` | 接收 Chatwoot Webhook |
| POST | `/api/chat` | 直接聊天接口（测试） |
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |
| GET | `/` | 服务信息 |

详细 API 文档见 [API.md](./API.md)

## 核心功能

### 1. Webhook 处理

接收 Chatwoot 的 `message_created` 事件，自动处理用户消息：

1. 意图识别（关键词匹配）
2. 调用 Dify AI 获取回复
3. 根据置信度判断是否转人工
4. 发送回复或转接人工客服

### 2. 智能转人工

以下情况自动转人工：

- 用户消息包含转人工关键词（"人工"、"投诉"等）
- AI 回复置信度低于阈值（默认 0.7）
- AI 回复内容建议转人工

转人工时会：
- 添加标签 `needs_human` 和 `ai_handoff`
- 发送私有备注给客服（包含转人工原因）
- 自动分配给在线客服

### 3. 监控指标

暴露 Prometheus 格式的监控指标：

- `message_counter`: 消息处理总数
- `handoff_counter`: 转人工总数
- `ai_response_time`: AI 响应时间
- `chatwoot_api_time`: Chatwoot API 调用时间

访问 `http://localhost:8000/metrics` 查看指标。

## 开发

### 运行测试

```bash
# 运行所有测试
pytest

# 运行指定测试
pytest tests/test_integration.py -v

# 生成覆盖率报告
pytest --cov=src --cov-report=html
```

### 代码检查

```bash
# 格式化代码
black src/ tests/

# Lint 检查
ruff check src/ tests/

# 类型检查
mypy src/
```

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t bridge-service:latest .

# 运行容器
docker run -d \
  --name bridge-service \
  -p 8000:8000 \
  --env-file .env \
  bridge-service:latest
```

### 生产配置建议

- 使用 Gunicorn + Uvicorn workers
- 配置反向代理（Nginx）
- 启用 HTTPS
- 配置日志轮转
- 设置监控告警

## 故障排查

### Dify API 调用失败

检查：
1. `DIFY_API_KEY` 是否正确
2. Dify 服务是否运行
3. 网络连接是否正常

```bash
# 测试 Dify 连接
curl -X POST http://localhost:5001/v1/chat-messages \
  -H "Authorization: Bearer <DIFY_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"query": "测试", "user": "test"}'
```

### Chatwoot Webhook 不触发

检查：
1. Chatwoot 中 Webhook URL 配置是否正确
2. Bridge Service 是否可从 Chatwoot 访问
3. 查看 Bridge Service 日志

```bash
# 手动测试 Webhook
curl -X POST http://localhost:8000/webhook/chatwoot \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/webhook_payload.json
```

## 更多信息

- [技术方案](../企业级AI客服系统技术方案.md)
- [运维手册](../运维手册.md)
- [API 文档](./API.md)

## License

MIT
