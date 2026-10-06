import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { Input } from '@ai-cs/shared/components';
import {
  fetchAgentCredentials,
  fetchConfig,
  fetchWidgetSnippet,
  updateAgentCredentials,
  updateConfigBatch,
} from '@ai-cs/shared/api';

const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: 'layout-dashboard' },
  { path: '/agents', label: '客服管理', icon: 'users' },
  { path: '/contacts', label: '客户管理', icon: 'user' },
  { path: '/ai', label: 'AI管理', icon: 'bot' },
  { path: '/settings', label: '系统设置', icon: 'settings' },
];

/** 按点号路径读取嵌套值，如 getPath(config, 'ai.confidence_threshold') */
function getPath(obj: Record<string, any>, path: string): any {
  return path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
}

/** 按点号路径写入嵌套值（不可变更新） */
function setPath(obj: Record<string, any>, path: string, value: any): Record<string, any> {
  const keys = path.split('.');
  const clone = structuredClone(obj) as Record<string, any>;
  let cur: Record<string, any> = clone;
  for (let i = 0; i < keys.length - 1; i++) {
    if (typeof cur[keys[i]] !== 'object' || cur[keys[i]] === null) {
      cur[keys[i]] = {};
    }
    cur = cur[keys[i]];
  }
  cur[keys[keys.length - 1]] = value;
  return clone;
}

export function SettingsPage() {
  const [activeNav, setActiveNav] = useState('settings');
  const [activeTab, setActiveTab] = useState<'basic' | 'security' | 'ai' | 'integrations' | 'advanced'>('basic');
  const [config, setConfig] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [widgetSnippet, setWidgetSnippet] = useState('');
  const [agentConfigured, setAgentConfigured] = useState(false);
  const [agentUsername, setAgentUsername] = useState('agent');
  const [agentPassword, setAgentPassword] = useState('');
  const [agentPasswordConfirm, setAgentPasswordConfirm] = useState('');
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [credentialMsg, setCredentialMsg] = useState('');
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    fetchConfig()
      .then((res) => setConfig(res as Record<string, any>))
      .catch(() => setConfig({}))
      .finally(() => setLoading(false));

    fetchAgentCredentials()
      .then((status) => {
        setAgentConfigured(status.configured);
        setAgentUsername(status.username);
      })
      .catch(() => setCredentialMsg('无法读取客服凭据状态'));
  }, []);

  const handleNavClick = (path: string) => {
    setActiveNav(path.replace('/', ''));
    navigate(path);
  };

  /** 保存一组点号路径配置 */
  const handleSave = useCallback(
    async (keys: string[]) => {
      setSaving(true);
      setSaveMsg('');
      try {
        const payload: Record<string, any> = {};
        for (const key of keys) payload[key] = getPath(config, key);
        await updateConfigBatch(payload);
        setSaveMsg('已保存 ✓');
      } catch {
        setSaveMsg('保存失败，请稍后重试');
      } finally {
        setSaving(false);
      }
    },
    [config]
  );

  const val = (key: string) => getPath(config, key);
  const setVal = (key: string, value: any) => setConfig((prev) => setPath(prev, key, value));

  const saveAgentCredentials = async () => {
    const normalizedUsername = agentUsername.trim();
    setCredentialMsg('');
    if (normalizedUsername.length < 3) {
      setCredentialMsg('客服用户名至少3位');
      return;
    }
    if (agentPassword.length < 12) {
      setCredentialMsg('客服密码至少12位');
      return;
    }
    if (agentPassword !== agentPasswordConfirm) {
      setCredentialMsg('两次输入的客服密码不一致');
      return;
    }

    setCredentialSaving(true);
    try {
      const status = await updateAgentCredentials(normalizedUsername, agentPassword);
      setAgentConfigured(status.configured);
      setAgentUsername(status.username);
      setAgentPassword('');
      setAgentPasswordConfirm('');
      setCredentialMsg('客服登录凭据已更新，旧刷新会话已撤销');
    } catch (reason) {
      setCredentialMsg(reason instanceof Error ? reason.message : '客服凭据更新失败');
    } finally {
      setCredentialSaving(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#f3f4f6' }}>
      <aside style={{ width: '240px', backgroundColor: '#1f2937', display: 'flex', flexDirection: 'column', color: '#ffffff' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid #374151' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '9px', backgroundColor: '#6366f1', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600 }}>
              AI
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>AI客服管理</h1>
              <p style={{ margin: '2px 0 0', fontSize: '11px', color: '#9ca3af' }}>后台系统</p>
            </div>
          </div>
        </div>

        <nav style={{ padding: '12px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {navItems.map((item) => (
              <button
                key={item.path}
                onClick={() => handleNavClick(item.path)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  backgroundColor: activeNav === item.path.replace('/', '') ? '#6366f1' : 'transparent',
                  color: activeNav === item.path.replace('/', '') ? '#ffffff' : '#d1d5db',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: '14px',
                  textAlign: 'left',
                  transition: 'all 0.2s',
                }}
              >
                {item.icon === 'layout-dashboard' && (
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect width="7" height="7" x="3" y="3" rx="1" />
                    <rect width="7" height="7" x="14" y="3" rx="1" />
                    <rect width="7" height="7" x="14" y="14" rx="1" />
                    <rect width="7" height="7" x="3" y="14" rx="1" />
                  </svg>
                )}
                {item.icon === 'users' && (
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                )}
                {item.icon === 'user' && (
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                )}
                {item.icon === 'bot' && (
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect width="18" height="10" x="3" y="7" rx="2" />
                    <path d="M12 7V4" />
                    <path d="M8 7V4" />
                    <path d="M16 7V4" />
                    <circle cx="9" cy="12" r="0.5" />
                    <circle cx="15" cy="12" r="0.5" />
                    <path d="M9 16h6" />
                  </svg>
                )}
                {item.icon === 'settings' && (
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
                {item.label}
              </button>
            ))}
          </div>
        </nav>

        <div style={{ flex: 1 }} />

        <div style={{ padding: '16px', borderTop: '1px solid #374151' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#374151', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, fontSize: '13px' }}>
              {user?.username?.charAt(0) || 'A'}
            </div>
            <div style={{ flex: 1 }}>
              <p style={{ margin: 0, fontSize: '13px', fontWeight: 500 }}>{user?.username}</p>
              <p style={{ margin: '2px 0 0', fontSize: '11px', color: '#9ca3af' }}>管理员</p>
            </div>
            <Button variant="ghost" size="sm" onClick={logout} style={{ color: '#d1d5db' }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </Button>
          </div>
        </div>
      </aside>

      <main style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#1f2937' }}>系统设置</h1>
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#6b7280' }}>配置系统参数和集成设置</p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', marginBottom: '24px' }}>
          <Button variant={activeTab === 'basic' ? 'outline' : 'ghost'} size="sm" onClick={() => setActiveTab('basic')}>基本设置</Button>
          <Button variant={activeTab === 'security' ? 'outline' : 'ghost'} size="sm" onClick={() => setActiveTab('security')}>登录安全</Button>
          <Button variant={activeTab === 'ai' ? 'outline' : 'ghost'} size="sm" onClick={() => setActiveTab('ai')}>AI配置</Button>
          <Button variant={activeTab === 'integrations' ? 'outline' : 'ghost'} size="sm" onClick={() => setActiveTab('integrations')}>集成设置</Button>
          <Button variant={activeTab === 'advanced' ? 'outline' : 'ghost'} size="sm" onClick={() => setActiveTab('advanced')}>高级设置</Button>
        </div>

        {loading && (
          <Card padding="md">
            <p style={{ margin: 0, fontSize: '13px', color: '#9ca3af', textAlign: 'center', padding: '24px 0' }}>
              加载配置...
            </p>
          </Card>
        )}

        {!loading && activeTab === 'basic' && (
          <Card padding="lg">
            <h2 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>基本设置</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
              <div>
                <Input
                  label="缓存过期时间（秒）"
                  type="number"
                  value={val('cache.ttl') ?? ''}
                  onChange={(e) => setVal('cache.ttl', Number(e.target.value))}
                />
              </div>
              <div>
                <Input
                  label="每分钟请求上限"
                  type="number"
                  value={val('rate_limit.requests_per_minute') ?? ''}
                  onChange={(e) => setVal('rate_limit.requests_per_minute', Number(e.target.value))}
                />
              </div>
            </div>

            <div style={{ marginTop: '24px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>
                转人工关键词（逗号分隔）
              </label>
              <textarea
                value={Array.isArray(val('handoff.keywords')) ? (val('handoff.keywords') as string[]).join('，') : ''}
                onChange={(e) => setVal('handoff.keywords', e.target.value.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean))}
                style={{
                  width: '100%',
                  minHeight: '80px',
                  padding: '12px',
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  fontSize: '14px',
                  outline: 'none',
                  resize: 'vertical',
                }}
              />
            </div>

            <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
              <input
                type="checkbox"
                id="enable-cache"
                checked={Boolean(val('cache.enabled'))}
                onChange={(e) => setVal('cache.enabled', e.target.checked)}
                style={{ width: '18px', height: '18px' }}
              />
              <label htmlFor="enable-cache" style={{ fontSize: '14px', color: '#374151' }}>启用缓存</label>
            </div>

            <div style={{ marginTop: '24px', display: 'flex', gap: '12px', alignItems: 'center' }}>
              <Button
                type="button"
                variant="primary"
                loading={saving}
                onClick={() => handleSave(['cache.ttl', 'cache.enabled', 'rate_limit.requests_per_minute', 'handoff.keywords'])}
              >
                保存设置
              </Button>
              {saveMsg && <span style={{ fontSize: '13px', color: '#16a34a' }}>{saveMsg}</span>}
            </div>
          </Card>
        )}

        {!loading && activeTab === 'security' && (
          <Card padding="lg">
            <h2 style={{ margin: '0 0 8px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>客服登录安全</h2>
            <p style={{ margin: '0 0 24px', fontSize: '13px', color: agentConfigured ? '#16a34a' : '#dc2626' }}>
              {agentConfigured ? '已配置强凭据' : '尚未配置，客服工作台当前无法登录'}
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
              <Input
                label="客服用户名"
                value={agentUsername}
                onChange={(event) => setAgentUsername(event.target.value)}
              />
              <div />
              <Input
                label="新密码（至少12位）"
                type="password"
                value={agentPassword}
                onChange={(event) => setAgentPassword(event.target.value)}
              />
              <Input
                label="确认新密码"
                type="password"
                value={agentPasswordConfirm}
                onChange={(event) => setAgentPasswordConfirm(event.target.value)}
              />
            </div>
            <div style={{ marginTop: '24px', display: 'flex', gap: '12px', alignItems: 'center' }}>
              <Button type="button" variant="primary" loading={credentialSaving} onClick={saveAgentCredentials}>
                {agentConfigured ? '轮换凭据' : '设置凭据'}
              </Button>
              {credentialMsg && <span role="status" style={{ fontSize: '13px', color: credentialMsg.includes('已更新') ? '#16a34a' : '#dc2626' }}>{credentialMsg}</span>}
            </div>
            <p style={{ marginTop: '16px', fontSize: '12px', color: '#6b7280' }}>
              更新后，已签发的客服刷新会话会立即失效，客服需使用新凭据重新登录。
            </p>
          </Card>
        )}

        {!loading && activeTab === 'ai' && (
          <Card padding="lg">
            <h2 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>AI配置</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
              <div>
                <Input
                  label="人工转接置信度阈值（0-1）"
                  type="number"
                  step="0.05"
                  min={0}
                  max={1}
                  value={val('ai.confidence_threshold') ?? ''}
                  onChange={(e) => setVal('ai.confidence_threshold', Number(e.target.value))}
                />
              </div>
              <div>
                <Input
                  label="AI 最大重试次数"
                  type="number"
                  value={val('ai.max_retries') ?? ''}
                  onChange={(e) => setVal('ai.max_retries', Number(e.target.value))}
                />
              </div>
              <div>
                <Input
                  label="AI 请求超时（秒）"
                  type="number"
                  value={val('ai.timeout') ?? ''}
                  onChange={(e) => setVal('ai.timeout', Number(e.target.value))}
                />
              </div>
              <div>
                <Input
                  label="连续未解决转人工阈值"
                  type="number"
                  value={val('handoff.unresolved_threshold') ?? ''}
                  onChange={(e) => setVal('handoff.unresolved_threshold', Number(e.target.value))}
                />
              </div>
            </div>

            <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
              <input
                type="checkbox"
                id="enable-handoff"
                checked={Boolean(val('handoff.auto_assign'))}
                onChange={(e) => setVal('handoff.auto_assign', e.target.checked)}
                style={{ width: '18px', height: '18px' }}
              />
              <label htmlFor="enable-handoff" style={{ fontSize: '14px', color: '#374151' }}>转人工后自动分配坐席</label>
            </div>

            <div style={{ marginTop: '24px', display: 'flex', gap: '12px', alignItems: 'center' }}>
              <Button
                type="button"
                variant="primary"
                loading={saving}
                onClick={() => handleSave(['ai.confidence_threshold', 'ai.max_retries', 'ai.timeout', 'handoff.unresolved_threshold', 'handoff.auto_assign'])}
              >
                保存配置
              </Button>
              {saveMsg && <span style={{ fontSize: '13px', color: '#16a34a' }}>{saveMsg}</span>}
            </div>
            <p style={{ marginTop: '12px', fontSize: '12px', color: '#9ca3af' }}>
              提示：AI 模型 / API 密钥等模型参数请在「AI 管理」页配置。
            </p>
          </Card>
        )}

        {!loading && activeTab === 'integrations' && (
          <Card padding="lg">
            <h2 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>集成设置</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderRadius: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div><p style={{ margin: 0, fontSize: '14px', fontWeight: 500 }}>网页 Widget</p><p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>获取当前站点的一行嵌入代码</p></div>
                  <Button size="sm" variant="outline" onClick={async () => {
                    try { setWidgetSnippet((await fetchWidgetSnippet()).snippet); }
                    catch (reason) { setSaveMsg(reason instanceof Error ? reason.message : '获取失败'); }
                  }}>生成代码</Button>
                </div>
                {widgetSnippet && <div style={{ marginTop: 12 }}><textarea readOnly value={widgetSnippet} aria-label="Widget 嵌入代码" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} /><Button size="sm" onClick={() => navigator.clipboard.writeText(widgetSnippet)}>复制代码</Button></div>}
              </div>
              <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>微信公众号</p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>接入微信公众号消息</p>
                </div>
                <Button variant="outline" size="sm" disabled>配置</Button>
              </div>

              <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>钉钉</p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>接入钉钉消息</p>
                </div>
                <Button variant="outline" size="sm" disabled>配置</Button>
              </div>

              <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>邮件通知</p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>配置SMTP邮件服务</p>
                </div>
                <Button variant="outline" size="sm" disabled>配置</Button>
              </div>

              <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>短信通知</p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>配置短信服务</p>
                </div>
                <Button variant="outline" size="sm" disabled>配置</Button>
              </div>
            </div>
          </Card>
        )}

        {!loading && activeTab === 'advanced' && (
          <Card padding="lg">
            <h2 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>高级设置</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
              <div>
                <Input
                  label="限流突发上限"
                  type="number"
                  value={val('rate_limit.burst') ?? ''}
                  onChange={(e) => setVal('rate_limit.burst', Number(e.target.value))}
                />
              </div>
            </div>

            <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
              <input
                type="checkbox"
                id="enable-auto-assign"
                checked={Boolean(val('handoff.auto_assign'))}
                onChange={(e) => setVal('handoff.auto_assign', e.target.checked)}
                style={{ width: '18px', height: '18px' }}
              />
              <label htmlFor="enable-auto-assign" style={{ fontSize: '14px', color: '#374151' }}>启用自动分配</label>
            </div>

            <div style={{ marginTop: '24px', display: 'flex', gap: '12px', alignItems: 'center' }}>
              <Button
                type="button"
                variant="primary"
                loading={saving}
                onClick={() => handleSave(['rate_limit.burst', 'handoff.auto_assign'])}
              >
                保存设置
              </Button>
              {saveMsg && <span style={{ fontSize: '13px', color: '#16a34a' }}>{saveMsg}</span>}
            </div>
          </Card>
        )}
      </main>
    </div>
  );
}
