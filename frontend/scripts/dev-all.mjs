// 并发启动三个前端开发服务器 (widget/agent/admin)
// 背景：monorepo 根部 `turbo run dev` 在 Windows 上会启动后立即退出
//（turbo 1.12 persistent 任务 bug，且 node_modules 混用 pnpm/npm 导致 turbo 异常）。
// 本脚本用 Node 原生 child_process 分别拉起三个 vite，零新增依赖。
//
// 用法: npm run dev   (等价于 node scripts/dev-all.mjs)

import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const apps = [
  { name: 'widget', port: 5173 },
  { name: 'agent', port: 5174 },
  { name: 'admin', port: 5175 },
];

const children = [];

for (const app of apps) {
  const appDir = path.join(root, 'apps', app.name);
  const npxCmd = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const child = spawn(
    npxCmd,
    ['vite', '--port', String(app.port), '--strictPort'],
    // Windows 上 spawn .cmd 需要 shell: true，否则报 EINVAL
    { cwd: appDir, stdio: ['ignore', 'pipe', 'pipe'], shell: process.platform === 'win32' }
  );

  child.stdout.on('data', (d) => process.stdout.write(`[${app.name}] ${d}`));
  child.stderr.on('data', (d) => process.stderr.write(`[${app.name}] ${d}`));
  child.on('exit', (code, signal) => {
    console.log(`[${app.name}] 退出 code=${code} signal=${signal}`);
  });

  children.push(child);
}

function shutdown() {
  for (const c of children) {
    try { c.kill(); } catch { /* 忽略 */ }
  }
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

console.log(`已启动 ${apps.length} 个前端 dev server，Ctrl+C 停止`);
console.log(`Widget: http://localhost:5173  Agent: http://localhost:5174  Admin: http://localhost:5175`);
