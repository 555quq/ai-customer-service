import { createRoot } from 'react-dom/client';
import { RouterApp } from './RouterApp';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('未找到 #root 挂载节点');
}

createRoot(rootElement).render(<RouterApp />);