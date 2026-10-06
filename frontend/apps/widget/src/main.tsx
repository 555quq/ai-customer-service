import { createRoot } from 'react-dom/client';
import { App } from './App';
import './kiki-theme.css';

const rootElement = document.getElementById('ai-customer-service-container');
if (rootElement) {
  createRoot(rootElement).render(<App />);
}
