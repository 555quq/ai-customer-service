# Chatwoot Widget 集成指南

## 概述

Chatwoot Widget 是一个可嵌入任何网站的聊天窗口组件，用户可以通过它与 AI 客服或人工客服进行对话。

## 快速开始

### 1. 获取 Website Token

1. 登录 Chatwoot 管理后台（默认：http://localhost:3000）
2. 进入 `设置` → `收件箱` → 选择网站收件箱
3. 点击 `设置` 标签
4. 复制 `Website Token`

### 2. 集成到网页

将以下代码添加到网页的 `</body>` 标签前：

```html
<script>
  (function(d,t) {
    var BASE_URL="http://localhost:3000";
    var g=d.createElement(t),s=d.getElementsByTagName(t)[0];
    g.src=BASE_URL+"/packs/js/sdk.js";
    s.parentNode.insertBefore(g,s);
    g.onload=function(){
      window.chatwootSDK.run({
        websiteToken: 'YOUR_WEBSITE_TOKEN',
        baseUrl: BASE_URL
      })
    }
  })(document,"script");
</script>
```

**替换参数**:
- `YOUR_WEBSITE_TOKEN`: 替换为步骤1获取的 Token
- `BASE_URL`: 替换为实际的 Chatwoot 地址

### 3. 配置 Webhook

为了让 AI 自动回复，需要配置 Webhook：

1. Chatwoot 管理后台 → `设置` → `集成` → `Webhooks`
2. 点击 `添加新的 Webhook`
3. 填写配置：
   - **URL**: `http://bridge-service:8000/webhook/chatwoot`
   - **事件**: 选择 `message_created`
4. 点击保存

## 高级配置

### 自定义用户信息

```javascript
window.$chatwoot.setUser('USER_ID', {
  email: 'user@example.com',
  name: '张三',
  avatar_url: 'https://example.com/avatar.jpg',
  phone_number: '+86 138 0000 0000',
  // 自定义属性
  custom_attributes: {
    plan: 'premium',
    company: 'Acme Inc'
  }
});
```

### 控制 Widget 显示

```javascript
// 打开聊天窗口
window.$chatwoot.toggle('open');

// 关闭聊天窗口
window.$chatwoot.toggle('close');

// 切换显示/隐藏
window.$chatwoot.toggle();
```

### 设置语言

```javascript
window.chatwootSettings = {
  locale: 'zh_CN',  // 中文
  // locale: 'en',  // 英文
};
```

### 自定义外观

在 Chatwoot 管理后台 → 收件箱设置中可以自定义：

- **Widget 颜色**: 主题色、按钮颜色
- **欢迎消息**: 用户打开时的第一条消息
- **Widget 位置**: 左下角或右下角
- **Widget 图标**: 自定义图标
- **团队头像**: 显示客服团队照片

### 事件监听

```javascript
// Widget 加载完成
window.addEventListener('chatwoot:ready', function() {
  console.log('Chatwoot 已就绪');
});

// Widget 打开
window.addEventListener('chatwoot:open', function() {
  console.log('聊天窗口已打开');
});

// Widget 关闭
window.addEventListener('chatwoot:close', function() {
  console.log('聊天窗口已关闭');
});

// 新消息到达
window.addEventListener('chatwoot:on-message', function(event) {
  console.log('收到新消息:', event.detail);
});
```

### 发送自定义事件

```javascript
// 用于跟踪用户行为
window.$chatwoot.sendEvent('product_viewed', {
  product_id: '12345',
  product_name: 'iPhone 14',
  price: 5999
});
```

## 集成示例

### React 集成

```jsx
import { useEffect } from 'react';

function App() {
  useEffect(() => {
    // 加载 Chatwoot Widget
    (function(d,t) {
      var BASE_URL="http://localhost:3000";
      var g=d.createElement(t),s=d.getElementsByTagName(t)[0];
      g.src=BASE_URL+"/packs/js/sdk.js";
      g.async=true;
      s.parentNode.insertBefore(g,s);
      g.onload=function(){
        window.chatwootSDK.run({
          websiteToken: process.env.REACT_APP_CHATWOOT_TOKEN,
          baseUrl: BASE_URL
        })
      }
    })(document,"script");
  }, []);

  const handleOpenChat = () => {
    if (window.$chatwoot) {
      window.$chatwoot.toggle('open');
    }
  };

  return (
    <div>
      <h1>我的网站</h1>
      <button onClick={handleOpenChat}>联系客服</button>
    </div>
  );
}
```

### Vue 集成

```vue
<template>
  <div>
    <h1>我的网站</h1>
    <button @click="openChat">联系客服</button>
  </div>
</template>

<script>
export default {
  mounted() {
    this.loadChatwoot();
  },
  
  methods: {
    loadChatwoot() {
      (function(d,t) {
        var BASE_URL="http://localhost:3000";
        var g=d.createElement(t),s=d.getElementsByTagName(t)[0];
        g.src=BASE_URL+"/packs/js/sdk.js";
        g.async=true;
        s.parentNode.insertBefore(g,s);
        g.onload=function(){
          window.chatwootSDK.run({
            websiteToken: process.env.VUE_APP_CHATWOOT_TOKEN,
            baseUrl: BASE_URL
          })
        }
      })(document,"script");
    },
    
    openChat() {
      if (window.$chatwoot) {
        window.$chatwoot.toggle('open');
      }
    }
  }
}
</script>
```

## 测试

### 本地测试

1. 在浏览器中打开 `examples/chatwoot-widget-demo.html`
2. 点击右下角的聊天图标
3. 发送测试消息
4. 验证 AI 是否正常回复

### 生产环境测试清单

- [ ] Widget 正常加载和显示
- [ ] 可以发送和接收消息
- [ ] AI 自动回复工作正常
- [ ] 低置信度会转人工
- [ ] 人工客服可以接管对话
- [ ] 文件上传功能正常
- [ ] 移动端适配正常
- [ ] 不同浏览器兼容性测试

## 常见问题

### 1. Widget 不显示

**检查项**:
- Chatwoot 服务是否运行
- BASE_URL 是否正确
- Website Token 是否正确
- 浏览器控制台是否有错误

### 2. 发送消息后没有 AI 回复

**检查项**:
- Bridge Service 是否运行
- Webhook 是否配置正确
- Dify API Key 是否有效
- 查看 Bridge Service 日志

### 3. 跨域问题

如果遇到 CORS 错误，需要在 Nginx 配置中添加：

```nginx
add_header Access-Control-Allow-Origin *;
add_header Access-Control-Allow-Methods 'GET, POST, OPTIONS';
add_header Access-Control-Allow-Headers 'Content-Type, Authorization';
```

### 4. HTTPS 环境集成

在生产环境中，确保：
- Chatwoot 使用 HTTPS
- 网页也使用 HTTPS
- BASE_URL 使用 `https://` 协议

## 性能优化

### 1. 异步加载

Widget 脚本已经是异步加载，不会阻塞页面渲染。

### 2. 延迟加载

如果想进一步优化首屏加载，可以延迟加载 Widget：

```javascript
// 页面加载3秒后再加载 Widget
setTimeout(function() {
  // Chatwoot 加载代码
}, 3000);
```

### 3. 按需加载

只在特定页面加载 Widget：

```javascript
// 仅在产品页面加载
if (window.location.pathname.includes('/products')) {
  // Chatwoot 加载代码
}
```

## 安全建议

1. **不要在前端暴露敏感信息**: Website Token 是公开的，没问题
2. **验证用户输入**: 后端需要验证用户提交的数据
3. **限制消息频率**: 使用 API 限流防止滥用
4. **监控异常行为**: 记录并监控可疑的对话行为

## 相关资源

- [Chatwoot 官方文档](https://www.chatwoot.com/docs)
- [Chatwoot SDK 文档](https://www.chatwoot.com/docs/product/channels/live-chat/sdk/setup)
- [示例页面](./chatwoot-widget-demo.html)
- [技术方案](../企业级AI客服系统技术方案.md)

## 支持

如有问题，请查看：
- [运维手册](../运维手册.md)
- [故障排查指南](../bridge-service/测试报告.md)
