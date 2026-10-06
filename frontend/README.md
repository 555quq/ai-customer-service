# AI 智能客服 - 前端演示

基于 React 18 + TypeScript + Vite 构建的 AI 智能客服前端演示项目，不依赖任何 UI 组件库或图表库，全部样式由纯 CSS 实现。

## 技术栈

- React 18.3
- TypeScript 5.4
- Vite 5.2
- @vitejs/plugin-react
- 纯 CSS（无 UI / 图表库）

## 目录结构

```
frontend/
├── index.html            # HTML 入口，挂载点 #root
├── package.json
├── tsconfig.json         # 应用 TS 配置（严格模式）
├── tsconfig.node.json    # vite.config 专用 TS 配置
├── vite.config.ts        # Vite 配置，dev 端口 5173
└── src/
    ├── main.tsx          # 应用入口，渲染到 #root
    └── styles/
        └── tokens.css    # 设计系统令牌（颜色 / 间距 / 字体等）
```

## 如何运行

```bash
# 安装依赖
npm install

# 启动开发服务器（默认 http://localhost:5173）
npm run dev

# 生产构建（先 tsc 类型检查再打包）
npm run build

# 预览生产构建产物
npm run preview

# 仅做类型检查，不输出文件
npm run typecheck
```

## 界面说明

演示包含三个核心界面：

1. **对话界面** —— 用户与 AI 客服的实时问答，展示消息流、输入框与会话状态。
2. **工单 / 会话列表** —— 历史会话与工单概览，支持查看与切换不同会话。
3. **数据看板** —— 客服指标概览（如会话量、解决率等），使用纯 CSS 呈现可视化，无图表库依赖。

## 设计系统

全局设计令牌集中在 `src/styles/tokens.css`，通过 CSS 自定义属性（CSS Variables）统一管理颜色、间距、圆角、字号与阴影等。所有组件样式均基于这些令牌，便于保持视觉一致性与主题维护。
