import { createElement } from 'react';
import type { WidgetConfig } from '@ai-cs/shared/types';
import { createRoot } from 'react-dom/client';
import { WidgetComponent } from '../components/WidgetComponent';
import { fetchWidgetPublicConfig } from '@ai-cs/shared/api';
import widgetCss from '../kiki-theme.css?inline';

const defaultConfig: Partial<WidgetConfig> = {
  brandName: '在线客服',
  welcomeMessage: '你好！有什么可以帮到您？',
  position: 'right',
  themeColor: '#6366f1',
  zIndex: 9999,
};

export async function initWidget(config: Partial<WidgetConfig>) {
  if (document.querySelector('[data-ai-customer-service-host]')) return;
  const apiUrl = (config.apiUrl || 'http://localhost:8000').replace(/\/$/, '');
  const host = document.createElement('div');
  host.dataset.aiCustomerServiceHost = 'true';
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = widgetCss;
  const widgetContainer = document.createElement('div');
  widgetContainer.id = 'ai-customer-service';
  shadow.append(style, widgetContainer);
  document.body.appendChild(host);
  try {
    let remoteConfig: Partial<WidgetConfig> = {};
    if (config.siteToken) {
      remoteConfig = await fetchWidgetPublicConfig(apiUrl, config.siteToken);
    }
    const mergedConfig: WidgetConfig = {
      ...defaultConfig,
      ...remoteConfig,
      ...config,
      apiUrl,
    } as WidgetConfig;
    const root = createRoot(widgetContainer);
    root.render(createElement(WidgetComponent, { config: mergedConfig }));
  } catch (error) {
    widgetContainer.innerHTML = '<div role="alert" style="position:fixed;right:24px;bottom:24px;padding:12px 16px;border-radius:8px;background:#fff1f2;color:#9f1239;box-shadow:0 8px 24px rgba(0,0,0,.15);font:14px sans-serif">客服组件暂时无法加载，请稍后重试。</div>';
    throw error;
  }
}
