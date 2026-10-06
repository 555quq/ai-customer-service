import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { Input } from '@ai-cs/shared/components';
import { updateAgentStatus, fetchAgentUsers } from '@ai-cs/shared/api';

const STATUS_OPTIONS = [
  { key: 'online', label: '在线', color: '#22c55e', desc: '可接收转人工会话' },
  { key: 'away', label: '离开', color: '#eab308', desc: '暂时离开，不接收新会话' },
  { key: 'busy', label: '忙碌', color: '#f97316', desc: '处理中，仅接收少量会话' },
  { key: 'offline', label: '离线', color: '#9ca3af', desc: '不接收任何会话' },
];

export function ProfilePage() {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    phone: '',
    signature: '',
  });
  const [status, setStatus] = useState('online');
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [agentName, setAgentName] = useState('');
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (user) {
      setFormData({
        username: user.username || '',
        email: '',
        phone: '',
        signature: '',
      });
    }
  }, [user]);

  // 获取当前客服在 Chatwoot 的名称（状态以 Chatwoot 客服名为身份标识）
  useEffect(() => {
    fetchAgentUsers()
      .then((agents) => {
        if (agents && agents.length > 0) {
          setAgentName(agents[0].name);
          setStatus(agents[0].status || 'online');
        }
      })
      .catch(() => {});
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleStatusChange = async (key: string) => {
    const identity = agentName || user?.username || '';
    if (!identity || statusUpdating) return;
    setStatusUpdating(true);
    try {
      await updateAgentStatus(identity, key);
      setStatus(key);
    } catch (e) {
      /* 忽略，保持原状态 */
    } finally {
      setStatusUpdating(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#f3f4f6' }}>
      <aside style={{ width: '280px', backgroundColor: '#ffffff', borderRight: '1px solid #e5e7eb', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid #e5e7eb' }}>
          <Button variant="ghost" size="sm" onClick={() => navigate('/workspace')} style={{ marginBottom: '12px' }}>
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 12H5" />
              <path d="M12 19l-7-7 7-7" />
            </svg>
            返回
          </Button>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '10px', backgroundColor: '#6366f1', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ffffff', fontWeight: 600 }}>
              AI
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>客服工作台</h1>
              <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>在线客服</p>
            </div>
          </div>
        </div>

        <div style={{ flex: 1 }} />

        <div style={{ padding: '16px', borderTop: '1px solid #e5e7eb' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '9px', backgroundColor: '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280', fontWeight: 600 }}>
              {user?.username?.charAt(0) || 'A'}
            </div>
            <div style={{ flex: 1 }}>
              <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>{user?.username}</p>
              <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#6b7280' }}>在线客服</p>
            </div>
          </div>
        </div>
      </aside>

      <main style={{ flex: 1, padding: '48px', overflowY: 'auto' }}>
        <div style={{ maxWidth: '600px', margin: '0 auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
            <div style={{ width: '80px', height: '80px', borderRadius: '20px', backgroundColor: '#6366f1', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#ffffff', fontWeight: 700, fontSize: '28px' }}>
              {user?.username?.charAt(0) || 'A'}
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#1f2937' }}>{user?.username}</h1>
              <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#6b7280' }}>在线客服</p>
            </div>
          </div>

          <Card padding="lg" style={{ marginBottom: '24px' }}>
            <h2 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>在线状态</h2>
            <p style={{ margin: '0 0 16px', fontSize: '12px', color: '#6b7280' }}>
              当前状态：<strong style={{ color: STATUS_OPTIONS.find((s) => s.key === status)?.color }}>{STATUS_OPTIONS.find((s) => s.key === status)?.label}</strong>
              {' '}（{STATUS_OPTIONS.find((s) => s.key === status)?.desc}）
            </p>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              {STATUS_OPTIONS.map((opt) => (
                <Button
                  key={opt.key}
                  variant={status === opt.key ? 'primary' : 'outline'}
                  size="sm"
                  disabled={statusUpdating}
                  onClick={() => handleStatusChange(opt.key)}
                  style={status === opt.key ? { backgroundColor: opt.color, borderColor: opt.color } : { color: opt.color, borderColor: opt.color }}
                >
                  {opt.label}
                </Button>
              ))}
            </div>
          </Card>

          <Card padding="lg" style={{ marginBottom: '24px' }}>
            <h2 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>个人信息</h2>
            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: '16px' }}>
                <Input
                  label="用户名"
                  value={formData.username}
                  onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  placeholder="请输入用户名"
                />
              </div>

              <div style={{ marginBottom: '16px' }}>
                <Input
                  label="邮箱"
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  placeholder="请输入邮箱"
                />
              </div>

              <div style={{ marginBottom: '16px' }}>
                <Input
                  label="手机号"
                  type="tel"
                  value={formData.phone}
                  onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                  placeholder="请输入手机号"
                />
              </div>

              <div style={{ marginBottom: '24px' }}>
                <Input
                  label="个性签名"
                  value={formData.signature}
                  onChange={(e) => setFormData({ ...formData, signature: e.target.value })}
                  placeholder="请输入个性签名"
                />
              </div>

              <Button type="submit" variant="primary">
                保存修改
              </Button>
            </form>
          </Card>

          <Card padding="lg">
            <h2 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>账号安全</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px', backgroundColor: '#f9fafb', borderRadius: '12px' }}>
                <div>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>修改密码</p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>定期更换密码以保护账号安全</p>
                </div>
                <Button variant="outline" size="sm">修改</Button>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px', backgroundColor: '#f9fafb', borderRadius: '12px' }}>
                <div>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>双因素认证</p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>增强账号安全性</p>
                </div>
                <Button variant="outline" size="sm">启用</Button>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px', backgroundColor: '#fef2f2', borderRadius: '12px' }}>
                <div>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#dc2626' }}>退出登录</p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#f87171' }}>将退出当前账号</p>
                </div>
                <Button variant="ghost" size="sm" onClick={handleLogout}>退出</Button>
              </div>
            </div>
          </Card>
        </div>
      </main>
    </div>
  );
}
