import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { Badge } from '@ai-cs/shared/components';
import { fetchAgentUsers, updateAgentStatus } from '@ai-cs/shared/api';

/** 客服列表项（由后端 /api/agent/agents 映射） */
interface AgentRow {
  id: string;
  username: string;
  email?: string;
  phone?: string;
  status: 'online' | 'away' | 'busy' | 'offline';
  role: string;
}

const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: 'layout-dashboard' },
  { path: '/agents', label: '客服管理', icon: 'users' },
  { path: '/contacts', label: '客户管理', icon: 'user' },
  { path: '/ai', label: 'AI管理', icon: 'bot' },
  { path: '/settings', label: '系统设置', icon: 'settings' },
];

export function AgentsPage() {
  const [activeNav, setActiveNav] = useState('agents');
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'online' | 'offline' | 'away'>('all');
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  // 从 Bridge Service 加载真实客服列表（Chatwoot 坐席）
  useEffect(() => {
    fetchAgentUsers()
      .then((res) => {
        setAgents(
          res.map((a: any) => ({
            id: String(a.id),
            username: a.name || `客服 ${a.id}`,
            email: a.email ?? '-',
            phone: a.phone ?? '-',
            status: a.status || 'offline',
            role: a.role || 'agent',
          }))
        );
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  /** 切换在线/离线状态（后端 Redis 持久化） */
  const handleToggleStatus = async (agent: AgentRow) => {
    const next = agent.status === 'online' ? 'offline' : 'online';
    try {
      await updateAgentStatus(agent.username, next);
      setAgents((prev) => prev.map((a) => (a.id === agent.id ? { ...a, status: next } : a)));
    } catch {
      // 忽略状态切换失败
    }
  };

  const filteredAgents = agents.filter((agent) => {
    const matchesSearch = agent.username.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         (agent.email ?? '').toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'all' || agent.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

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
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#1f2937' }}>客服管理</h1>
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#6b7280' }}>管理客服账号和权限</p>
          </div>
          <Button variant="primary" disabled title="客服账号由 Chatwoot 管理，暂不支持在后台新增">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14" />
              <path d="M5 12h14" />
            </svg>
            添加客服
          </Button>
        </div>

        <Card padding="md" style={{ marginBottom: '24px' }}>
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{ flex: 1 }}>
              <input
                type="text"
                placeholder="搜索客服姓名或邮箱..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  fontSize: '14px',
                  outline: 'none',
                  transition: 'border-color 0.2s',
                }}
                onFocus={(e) => (e.target.style.borderColor = '#6366f1')}
                onBlur={(e) => (e.target.style.borderColor = '#e5e7eb')}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Button variant={statusFilter === 'all' ? 'outline' : 'ghost'} size="sm" onClick={() => setStatusFilter('all')}>全部</Button>
              <Button variant={statusFilter === 'online' ? 'outline' : 'ghost'} size="sm" onClick={() => setStatusFilter('online')}>在线</Button>
              <Button variant={statusFilter === 'offline' ? 'outline' : 'ghost'} size="sm" onClick={() => setStatusFilter('offline')}>离线</Button>
              <Button variant={statusFilter === 'away' ? 'outline' : 'ghost'} size="sm" onClick={() => setStatusFilter('away')}>离开</Button>
            </div>
          </div>
        </Card>

        <Card padding="md">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
            {loading && (
              <p style={{ margin: 0, fontSize: '13px', color: '#9ca3af', gridColumn: '1 / -1', textAlign: 'center', padding: '24px 0' }}>
                加载客服列表...
              </p>
            )}
            {!loading && filteredAgents.length === 0 && (
              <p style={{ margin: 0, fontSize: '13px', color: '#9ca3af', gridColumn: '1 / -1', textAlign: 'center', padding: '24px 0' }}>
                暂无客服数据
              </p>
            )}
            {filteredAgents.map((agent) => (
              <div key={agent.id} style={{ padding: '20px', backgroundColor: '#f9fafb', borderRadius: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
                  <div style={{ width: '48px', height: '48px', borderRadius: '12px', backgroundColor: '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, color: '#6b7280', fontSize: '18px' }}>
                    {agent.username.charAt(2)}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontWeight: 600, color: '#1f2937', fontSize: '16px' }}>{agent.username}</span>
                      <Badge variant={agent.status === 'online' ? 'success' : agent.status === 'busy' || agent.status === 'away' ? 'warning' : 'default'} size="sm">
                        {agent.status === 'online' && '在线'}
                        {agent.status === 'busy' && '忙碌'}
                        {agent.status === 'away' && '离开'}
                        {agent.status === 'offline' && '离线'}
                      </Badge>
                    </div>
                    <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>{agent.role === 'administrator' ? '管理员' : '在线客服'}</p>
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#6b7280' }}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                      <polyline points="22,6 12,13 2,6" />
                    </svg>
                    {agent.email}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#6b7280' }}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
                    </svg>
                    {agent.phone}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleToggleStatus(agent)}
                    title={agent.status === 'online' ? '点击设为离线' : '点击设为在线'}
                  >
                    {agent.status === 'online' ? '设为离线' : '设为在线'}
                  </Button>
                  <Button variant="ghost" size="sm" disabled title="暂不支持编辑客服">编辑</Button>
                  <Button variant="ghost" size="sm" disabled style={{ color: '#ef4444' }} title="暂不支持删除">删除</Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </main>
    </div>
  );
}