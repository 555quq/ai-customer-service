import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@ai-cs/shared/api', () => ({
  fetchWidgetPublicConfig: vi.fn().mockResolvedValue({
    brandName: 'Acme 客服', welcomeMessage: '欢迎咨询', themeColor: '#123456',
    locale: 'zh-CN', theme: 'light', position: 'right',
  }),
}));

import { initWidget } from '../../lib/init';
import { fetchWidgetPublicConfig } from '@ai-cs/shared/api';

describe('initWidget 嵌入初始化', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('创建 Shadow DOM 并防止重复挂载', async () => {
    await initWidget({ apiUrl: 'https://service.example', siteToken: 'site-token' });
    await initWidget({ apiUrl: 'https://service.example', siteToken: 'site-token' });
    const hosts = document.querySelectorAll('[data-ai-customer-service-host]');
    expect(hosts).toHaveLength(1);
    const shadow = hosts[0].shadowRoot;
    expect(shadow).not.toBeNull();
    expect(shadow?.querySelector('style')).not.toBeNull();
    expect(shadow?.querySelector('#ai-customer-service')).not.toBeNull();
  });

  it('远程配置失败时在 Widget 内显示错误且不污染宿主页面', async () => {
    (fetchWidgetPublicConfig as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('offline'));
    await expect(initWidget({ apiUrl: 'https://service.example', siteToken: 'site-token' })).rejects.toThrow('offline');
    const host = document.querySelector('[data-ai-customer-service-host]');
    expect(host?.shadowRoot?.querySelector('[role="alert"]')).toHaveTextContent('客服组件暂时无法加载');
    expect(document.body.querySelector('[role="alert"]')).toBeNull();
  });
});
