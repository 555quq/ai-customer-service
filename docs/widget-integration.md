# Widget 集成

Admin 的 Widget 页面通过受管理员鉴权保护的 `/api/widget/snippet` 生成嵌入代码。

```html
<script
  src="https://widget.example.com/assets/widget.js"
  data-api-base="https://widget.example.com"
  data-site-token="SITE_TOKEN"
  data-theme="light"
  data-locale="zh-CN">
</script>
```

Widget 使用 Shadow DOM 隔离客户页面样式，通过 `/api/widget/session` 获取限定会话的短期能力 Token，并通过 `/api/chat`、`/api/chat/handoff` 和 `/ws/widget` 收发消息。

只有站点 Token 可以出现在嵌入代码中。模型 Key、Chatwoot Token、Admin/Agent 凭据和内部地址必须保留在服务器端。

生产环境建议为 Widget 单独使用公开子域名，严格限制可访问路由和 CORS Origin。
