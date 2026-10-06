# AlertManager 告警配置说明

## 概述

AlertManager 负责接收 Prometheus 发送的告警，进行分组、抑制、静默，并通过邮件、企业微信等渠道发送通知。

## 告警级别

系统定义了 3 个告警级别：

| 级别 | 标签 | 说明 | 通知方式 |
|------|------|------|---------|
| 🚨 紧急 | critical | 服务不可用、数据丢失等 | 企业微信 + 邮件 + 短信 |
| ⚠️ 警告 | warning | 性能下降、错误率升高等 | 邮件 |
| ℹ️ 信息 | info | 一般信息、统计数据等 | 邮件（低优先级）|

## 配置步骤

### 1. 邮件通知配置

编辑 `alertmanager/config.yml`：

```yaml
global:
  smtp_smarthost: 'smtp.qq.com:587'  # QQ邮箱
  smtp_from: 'your_email@qq.com'
  smtp_auth_username: 'your_email@qq.com'
  smtp_auth_password: 'your_authorization_code'  # QQ邮箱授权码
  smtp_require_tls: true
```

**获取 QQ 邮箱授权码**:
1. 登录 QQ 邮箱
2. 设置 → 账户 → POP3/IMAP/SMTP
3. 开启服务并生成授权码

### 2. 企业微信通知配置

```yaml
wechat_configs:
  - corp_id: 'ww1234567890abcdef'  # 企业ID
    to_party: '1'                   # 部门ID
    agent_id: '1000001'             # 应用ID
    api_secret: 'your_api_secret'   # 应用Secret
```

**获取企业微信配置**:
1. 登录[企业微信管理后台](https://work.weixin.qq.com/)
2. 应用管理 → 创建应用
3. 获取 AgentId 和 Secret
4. 企业信息 → 获取企业ID

### 3. 钉钉通知配置（可选）

```yaml
webhook_configs:
  - url: 'https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN'
    send_resolved: true
```

## 告警路由规则

### 当前配置的路由

```
所有告警
  ├─ severity=critical → 企业微信 + 邮件（5分钟重复）
  ├─ severity=warning  → 邮件（30分钟重复）
  └─ severity=info     → 邮件（2小时重复）
```

### 自定义路由示例

```yaml
routes:
  # Bridge Service 告警单独处理
  - match:
      service: bridge-service
    receiver: 'bridge-team'
    
  # 数据库告警发送给 DBA
  - match_re:
      alertname: '.*Database.*'
    receiver: 'dba-team'
```

## 告警抑制

当触发高级别告警时，自动抑制低级别的相关告警，避免告警风暴。

例如：
- 服务完全宕机（critical）时
- 抑制该服务的响应时间慢（warning）告警

## 告警静默

在维护期间临时静默告警：

```bash
# 通过 API 创建静默规则
curl -X POST http://localhost:9093/api/v1/silences \
  -H 'Content-Type: application/json' \
  -d '{
    "matchers": [
      {"name": "alertname", "value": "ServiceDown", "isRegex": false}
    ],
    "startsAt": "2026-06-11T10:00:00Z",
    "endsAt": "2026-06-11T12:00:00Z",
    "createdBy": "admin",
    "comment": "计划维护"
  }'
```

## 测试告警

### 1. 手动触发测试告警

```bash
# 发送测试告警到 AlertManager
curl -X POST http://localhost:9093/api/v1/alerts \
  -H 'Content-Type: application/json' \
  -d '[{
    "labels": {
      "alertname": "TestAlert",
      "severity": "warning",
      "instance": "localhost:8000"
    },
    "annotations": {
      "summary": "这是一个测试告警",
      "description": "用于验证 AlertManager 配置"
    }
  }]'
```

### 2. 触发实际告警

```bash
# 停止服务触发告警
docker-compose stop bridge-service

# 等待 1-2 分钟，Prometheus 会检测到并发送告警
# 查看 AlertManager UI: http://localhost:9093
```

## 告警模板自定义

创建 `alertmanager/templates/custom.tmpl`：

```
{{ define "custom.title" }}
[{{ .Status | toUpper }}] {{ .GroupLabels.alertname }}
{{ end }}

{{ define "custom.message" }}
{{ range .Alerts }}
告警: {{ .Labels.alertname }}
级别: {{ .Labels.severity }}
实例: {{ .Labels.instance }}
描述: {{ .Annotations.description }}
开始时间: {{ .StartsAt.Format "2006-01-02 15:04:05" }}
{{ if .EndsAt }}结束时间: {{ .EndsAt.Format "2006-01-02 15:04:05" }}{{ end }}
---
{{ end }}
{{ end }}
```

## 常见告警规则

### Bridge Service 相关

| 告警名称 | 触发条件 | 级别 |
|---------|---------|------|
| ServiceDown | 服务不可用 | critical |
| HighErrorRate | 错误率 > 5% | warning |
| SlowAIResponse | P95 响应时间 > 5s | warning |
| HighHandoffRate | 转人工率 > 50% | info |

### 基础设施相关

| 告警名称 | 触发条件 | 级别 |
|---------|---------|------|
| HostDown | 主机不可达 | critical |
| HighCPUUsage | CPU > 80% | warning |
| HighMemoryUsage | 内存 > 85% | warning |
| DiskSpaceLow | 磁盘 > 90% | critical |

## 告警接收测试清单

- [ ] 邮件通知正常接收
- [ ] 企业微信通知正常接收
- [ ] 紧急告警 5 分钟内收到
- [ ] 告警恢复通知收到
- [ ] 告警分组正常工作
- [ ] 告警抑制规则生效

## 故障排查

### 1. 邮件发送失败

**检查项**:
```bash
# 查看 AlertManager 日志
docker-compose logs alertmanager | grep -i error

# 测试 SMTP 连接
telnet smtp.example.com 587
```

**常见问题**:
- SMTP 密码错误（使用授权码而非登录密码）
- 防火墙阻止 SMTP 端口
- TLS 配置不正确

### 2. 企业微信收不到通知

**检查项**:
- Corp ID、Agent ID、API Secret 是否正确
- 应用是否启用并授权给部门
- 用户是否在指定部门中

### 3. 告警未触发

**检查项**:
```bash
# 检查 Prometheus 是否连接到 AlertManager
curl http://localhost:9090/api/v1/alertmanagers

# 检查告警规则是否加载
curl http://localhost:9090/api/v1/rules

# 查看当前触发的告警
curl http://localhost:9090/api/v1/alerts
```

## 最佳实践

1. **告警分级明确**: 不同级别的告警使用不同的通知渠道
2. **避免告警疲劳**: 合理设置重复间隔，避免频繁打扰
3. **告警可操作**: 每个告警都应该有明确的处理步骤
4. **定期测试**: 每月测试一次告警流程确保有效
5. **文档化**: 记录常见告警的处理步骤

## 相关文档

- [Prometheus 告警规则](../prometheus/alerts.yml)
- [运维手册](../运维手册.md)
- [AlertManager 官方文档](https://prometheus.io/docs/alerting/latest/alertmanager/)
