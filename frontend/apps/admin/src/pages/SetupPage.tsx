import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Card } from '@ai-cs/shared/components';
import { fetchSetupStatus, initializeSetup } from '@ai-cs/shared/api';

const steps = ['站点与账号', '模型服务', 'Chatwoot', 'AI 规则', '安全域名', '确认初始化'];

export function SetupPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [checking, setChecking] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    setupToken: '', siteName: '', brandColor: '#6366f1', locale: 'zh-CN' as 'zh-CN' | 'en-US',
    adminUsername: 'admin', adminPassword: '',
    agentUsername: 'agent', agentPassword: '', agentPasswordConfirm: '', provider: 'deepseek',
    apiBase: 'https://api.deepseek.com/v1', apiKey: '', model: 'deepseek-chat',
    chatwootUrl: 'http://localhost:3000', chatwootToken: '', accountId: '1', inboxId: '1',
    welcomeMessage: '你好！有什么可以帮到您？',
    systemPrompt: '请严格根据企业知识库回答客户问题；不确定时请转人工客服。',
    confidenceThreshold: '0.7', handoffKeywords: '人工,投诉,退款',
    allowedOrigins: 'http://localhost:5173', verifyConnections: true,
  });

  useEffect(() => {
    fetchSetupStatus()
      .then((status) => setInitialized(status.initialized))
      .catch((reason) => setError(reason instanceof Error ? reason.message : '无法连接 Bridge Service'))
      .finally(() => setChecking(false));
  }, []);

  const set = (key: keyof typeof form, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }));
  const canContinue = useMemo(() => {
    if (step === 0) {
      return form.setupToken
        && form.siteName
        && form.adminUsername
        && form.adminPassword.length >= 12
        && form.agentUsername
        && form.agentPassword.length >= 12
        && form.agentPassword === form.agentPasswordConfirm;
    }
    if (step === 1) return form.apiBase && form.apiKey && form.model;
    if (step === 2) return form.chatwootUrl && form.chatwootToken && Number(form.inboxId) > 0;
    if (step === 3) return form.systemPrompt.length >= 10;
    return true;
  }, [form, step]);

  const submit = async () => {
    setSubmitting(true); setError('');
    try {
      await initializeSetup({
        site: { name: form.siteName, brand_color: form.brandColor, locale: form.locale },
        model: { provider: form.provider, api_base: form.apiBase, api_key: form.apiKey, model: form.model },
        chatwoot: { base_url: form.chatwootUrl, api_token: form.chatwootToken, account_id: form.accountId, inbox_id: Number(form.inboxId) },
        admin: { username: form.adminUsername, password: form.adminPassword },
        agent: { username: form.agentUsername, password: form.agentPassword },
        ai_rules: {
          welcome_message: form.welcomeMessage, system_prompt: form.systemPrompt,
          confidence_threshold: Number(form.confidenceThreshold),
          handoff_keywords: form.handoffKeywords.split(',').map((item) => item.trim()).filter(Boolean),
        },
        allowed_origins: form.allowedOrigins.split(',').map((item) => item.trim()).filter(Boolean),
        verify_connections: form.verifyConnections,
      }, form.setupToken);
      setInitialized(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '初始化失败');
    } finally { setSubmitting(false); }
  };

  if (checking) return <div style={{ padding: 40 }}>正在检查初始化状态…</div>;
  if (initialized) return (
    <div style={shell}><Card padding="lg"><h1>系统已完成初始化</h1><p>请使用刚设置的管理员账号登录。</p><Button onClick={() => navigate('/login')}>前往登录</Button></Card></div>
  );

  const field = (label: string, key: keyof typeof form, type = 'text') => (
    <label style={labelStyle}>{label}<input type={type} value={String(form[key])} onChange={(event) => set(key, event.target.value)} style={inputStyle} /></label>
  );

  return (
    <div style={shell}>
      <Card padding="lg" style={{ width: 680, maxWidth: 'calc(100vw - 32px)' }}>
        <p style={{ margin: 0, color: '#6366f1', fontWeight: 600 }}>首次配置 · {step + 1}/{steps.length}</p>
        <h1 style={{ margin: '8px 0 24px' }}>{steps[step]}</h1>
        <div style={{ height: 4, background: '#e5e7eb', marginBottom: 24 }}><div style={{ width: `${((step + 1) / steps.length) * 100}%`, height: '100%', background: '#6366f1' }} /></div>

        {step === 0 && <div style={grid}>{field('一次性初始化 Token', 'setupToken', 'password')}{field('站点名称', 'siteName')}{field('管理员用户名', 'adminUsername')}{field('管理员密码（至少12位）', 'adminPassword', 'password')}{field('客服用户名', 'agentUsername')}{field('客服密码（至少12位）', 'agentPassword', 'password')}{field('确认客服密码', 'agentPasswordConfirm', 'password')}{field('品牌色', 'brandColor')}{form.agentPasswordConfirm && form.agentPassword !== form.agentPasswordConfirm && <p style={{ margin: 0, color: '#dc2626', fontSize: 13 }}>两次输入的客服密码不一致</p>}</div>}
        {step === 1 && <div style={grid}>{field('模型供应商', 'provider')}{field('API Base', 'apiBase')}{field('API Key', 'apiKey', 'password')}{field('模型名称', 'model')}</div>}
        {step === 2 && <div style={grid}>{field('Chatwoot 地址', 'chatwootUrl')}{field('API Token', 'chatwootToken', 'password')}{field('Account ID', 'accountId')}{field('Inbox ID（必须为 API 渠道）', 'inboxId', 'number')}</div>}
        {step === 3 && <div style={grid}>{field('欢迎语', 'welcomeMessage')}{field('系统提示词', 'systemPrompt')}{field('置信度阈值', 'confidenceThreshold', 'number')}{field('转人工关键词（逗号分隔）', 'handoffKeywords')}</div>}
        {step === 4 && <div style={grid}>{field('允许嵌入域名（逗号分隔）', 'allowedOrigins')}<label style={labelStyle}><span><input type="checkbox" checked={form.verifyConnections} onChange={(event) => set('verifyConnections', event.target.checked)} /> 初始化前验证模型和 Chatwoot</span></label></div>}
        {step === 5 && <div><p>系统将验证外部服务并保存配置。初始化成功后，本入口不能再次使用。</p><ul><li>站点：{form.siteName}</li><li>管理员：{form.adminUsername}</li><li>客服：{form.agentUsername}</li><li>模型：{form.provider} / {form.model}</li><li>Chatwoot：{form.chatwootUrl}</li><li>允许域名：{form.allowedOrigins}</li></ul></div>}

        {error && <p style={{ color: '#dc2626', background: '#fef2f2', padding: 12 }}>{error}</p>}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 28 }}>
          {step > 0 ? <Button variant="outline" onClick={() => setStep(step - 1)}>上一步</Button> : <Link to="/login">返回登录</Link>}
          {step < steps.length - 1 ? <Button disabled={!canContinue} onClick={() => setStep(step + 1)}>下一步</Button> : <Button loading={submitting} onClick={submit}>验证并初始化</Button>}
        </div>
      </Card>
    </div>
  );
}

const shell: React.CSSProperties = { minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f3f4f6', padding: 16 };
const grid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 18 };
const labelStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 7, fontSize: 14, fontWeight: 500, color: '#374151' };
const inputStyle: React.CSSProperties = { padding: '10px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14 };
