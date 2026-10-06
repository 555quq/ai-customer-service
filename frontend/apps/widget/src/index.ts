import { initWidget } from './lib/init';
export { initWidget } from './lib/init';
export { initWidget as init } from './lib/init';
export { App } from './App';

const script = document.currentScript as HTMLScriptElement | null;
if (script?.dataset.apiBase && script.dataset.siteToken) {
  initWidget({
    apiUrl: script.dataset.apiBase,
    siteToken: script.dataset.siteToken,
    theme: (script.dataset.theme as 'light' | 'dark' | undefined),
    locale: (script.dataset.locale as 'zh-CN' | 'en-US' | undefined),
  }).catch((error) => {
    console.error('[AI Customer Service] initialization failed', error);
  });
}
