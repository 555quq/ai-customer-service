import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { fetchContacts } from '@ai-cs/shared/api';
import type { AdminContact } from '@ai-cs/shared/types';

const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: 'layout-dashboard' },
  { path: '/agents', label: '客服管理', icon: 'users' },
  { path: '/contacts', label: '客户管理', icon: 'user' },
  { path: '/ai', label: 'AI管理', icon: 'bot' },
  { path: '/settings', label: '系统设置', icon: 'settings' },
];

/** 渠道显示名 */
function channelLabel(channel: string): string {
  const c = channel.toLowerCase();
  if (c === 'web' || c === 'app') return '网页';
  if (c === 'wechat') return '微信';
  if (c === 'whatsapp') return 'WhatsApp';
  return c || '其他';
}

export function ContactsPage() {
  const [activeNav, setActiveNav] = useState('contacts');
  const [contacts, setContacts] = useState<AdminContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  // 从 Bridge Service 加载真实客户列表（后端从 Chatwoot 会话聚合）
  useEffect(() => {
    fetchContacts()
      .then((res) => setContacts(res.contacts ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filteredContacts = contacts.filter((contact) =>
    contact.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    contact.email?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    contact.phone?.includes(searchTerm)
  );

  const handleNavClick = (path: string) => {
    setActiveNav(path.replace('/', ''));
    navigate(path);
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
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#1f2937' }}>客户管理</h1>
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#6b7280' }}>管理客户信息和会话记录</p>
          </div>
        </div>

        <Card padding="md" style={{ marginBottom: '24px' }}>
          <input
            type="text"
            placeholder="搜索客户姓名、邮箱或手机号..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              padding: '12px 16px',
              border: '1px solid #e5e7eb',
              borderRadius: '8px',
              fontSize: '14px',
              outline: 'none',
              transition: 'border-color 0.2s',
            }}
            onFocus={(e) => (e.target.style.borderColor = '#6366f1')}
            onBlur={(e) => (e.target.style.borderColor = '#e5e7eb')}
          />
        </Card>

        <Card padding="md">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                <th style={{ textAlign: 'left', padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: '#374151' }}>客户信息</th>
                <th style={{ textAlign: 'left', padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: '#374151' }}>联系方式</th>
                <th style={{ textAlign: 'left', padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: '#374151' }}>渠道</th>
                <th style={{ textAlign: 'left', padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: '#374151' }}>会话数</th>
                <th style={{ textAlign: 'left', padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: '#374151' }}>最近活跃</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} style={{ padding: '24px', textAlign: 'center', fontSize: '13px', color: '#9ca3af' }}>
                    加载客户列表...
                  </td>
                </tr>
              )}
              {!loading && filteredContacts.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ padding: '24px', textAlign: 'center', fontSize: '13px', color: '#9ca3af' }}>
                    暂无客户数据
                  </td>
                </tr>
              )}
              {filteredContacts.map((contact) => (
                <tr key={contact.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                  <td style={{ padding: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{ width: '40px', height: '40px', borderRadius: '10px', backgroundColor: '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, color: '#6b7280' }}>
                        {contact.name.charAt(0)}
                      </div>
                      <span style={{ fontWeight: 500, color: '#1f2937' }}>{contact.name}</span>
                    </div>
                  </td>
                  <td style={{ padding: '16px', fontSize: '14px', color: '#6b7280' }}>
                    {contact.email && <div>{contact.email}</div>}
                    {contact.phone && <div>{contact.phone}</div>}
                    {!contact.email && !contact.phone && <div>-</div>}
                  </td>
                  <td style={{ padding: '16px' }}>
                    <span style={{
                      padding: '4px 10px',
                      borderRadius: '9999px',
                      fontSize: '12px',
                      fontWeight: 500,
                      backgroundColor: contact.channel === 'web' || contact.channel === 'app' ? '#e0e7ff' : contact.channel === 'wechat' ? '#dcfce7' : '#fef9c3',
                      color: contact.channel === 'web' || contact.channel === 'app' ? '#4338ca' : contact.channel === 'wechat' ? '#16a34a' : '#ca8a04',
                    }}>
                      {channelLabel(contact.channel)}
                    </span>
                  </td>
                  <td style={{ padding: '16px', fontSize: '14px', color: '#1f2937', fontWeight: 500 }}>{contact.conversationCount}</td>
                  <td style={{ padding: '16px', fontSize: '14px', color: '#6b7280' }}>
                    {contact.lastActive ? new Date(contact.lastActive).toLocaleString() : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </main>
    </div>
  );
}