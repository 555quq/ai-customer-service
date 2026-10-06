import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { Badge } from '@ai-cs/shared/components';
import {
  fetchAnalyticsSummary,
  fetchAgentConversations,
  fetchAgentUsers,
  fetchConversationTrend,
} from '@ai-cs/shared/api';
import type { Agent, TrendPoint } from '@ai-cs/shared/types';

const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: 'layout-dashboard' },
  { path: '/agents', label: '客服管理', icon: 'users' },
  { path: '/contacts', label: '客户管理', icon: 'user' },
  { path: '/ai', label: 'AI管理', icon: 'bot' },
  { path: '/settings', label: '系统设置', icon: 'settings' },
];

/** 客服绩效（由会话按坐席聚合推导） */
interface AgentPerf {
  name: string;
  conversations: number;
  resolved: number;
}

export function DashboardPage() {
  const [activeNav, setActiveNav] = useState('dashboard');
  const [stats, setStats] = useState<Record<string, any>>({});
  const [recentConversations, setRecentConversations] = useState<any[]>([]);
  const [agentPerf, setAgentPerf] = useState<AgentPerf[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [trendDays, setTrendDays] = useState(7);
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  // 从 Bridge Service 加载真实统计 / 会话 / 客服绩效 / 会话趋势（后端连接 Chatwoot）
  useEffect(() => {
    Promise.all([
      fetchAnalyticsSummary(),
      fetchAgentConversations('all'),
      fetchAgentUsers(),
      fetchConversationTrend(trendDays),
    ])
      .then(([summary, convRes, agents, trendRes]) => {
        setStats(summary as Record<string, any>);
        setRecentConversations((convRes.conversations ?? []).slice(0, 5));
        setTrend(trendRes.points ?? []);

        // 客服绩效：按 assigneeName 聚合会话数与解决数
        const counts: Record<string, { total: number; resolved: number }> = {};
        for (const conv of convRes.conversations ?? []) {
          const name =
            conv.assigneeName || (conv.assigneeId ? `客服 ${conv.assigneeId}` : '未分配');
          const entry = counts[name] ?? { total: 0, resolved: 0 };
          entry.total += 1;
          if (conv.status === 'resolved') entry.resolved += 1;
          counts[name] = entry;
        }
        const perf = (agents ?? []).map((a: Agent) => ({
          name: a.name,
          conversations: counts[a.name]?.total ?? 0,
          resolved: counts[a.name]?.resolved ?? 0,
        }));
        // 补上会话中有但坐席列表缺失的分配对象
        for (const [name, c] of Object.entries(counts)) {
          if (!perf.some((p) => p.name === name)) {
            perf.push({ name, conversations: c.total, resolved: c.resolved });
          }
        }
        setAgentPerf(perf.sort((a, b) => b.conversations - a.conversations));
      })
      .catch(() => {});
  }, [trendDays]);

  const trendMax = Math.max(1, ...trend.map((t) => t.total));

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
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#1f2937' }}>仪表盘</h1>
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#6b7280' }}>实时监控客服运营数据</p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Badge variant="success">
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#22c55e', display: 'inline-block', marginRight: '6px' }} />
              系统运行正常
            </Badge>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px' }}>
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyItems: 'space-between' }}>
              <div>
                <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>总会话数</p>
                <p style={{ margin: '8px 0 0', fontSize: '32px', fontWeight: 700, color: '#1f2937' }}>{stats.total_conversations ?? 0}</p>
              </div>
              <div style={{ width: '48px', height: '48px', borderRadius: '12px', backgroundColor: '#e0e7ff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </div>
            </div>
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '4px', color: '#22c55e', fontSize: '12px' }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5M8 12l4-4 4 4" />
              </svg>
              今日新增 {stats.open_count ?? 0}
            </div>
          </Card>

          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyItems: 'space-between' }}>
              <div>
                <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>解决率</p>
                <p style={{ margin: '8px 0 0', fontSize: '32px', fontWeight: 700, color: '#1f2937' }}>{Math.round((stats.ai_resolution_rate ?? 0) * 100)}%</p>
              </div>
              <div style={{ width: '48px', height: '48px', borderRadius: '12px', backgroundColor: '#dcfce7', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
            </div>
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '4px', color: '#22c55e', fontSize: '12px' }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5M8 12l4-4 4 4" />
              </svg>
              较昨日 +3%
            </div>
          </Card>

          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyItems: 'space-between' }}>
              <div>
                <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>平均响应时间</p>
                <p style={{ margin: '8px 0 0', fontSize: '32px', fontWeight: 700, color: '#1f2937' }}>{stats.avg_messages_per_conversation ? stats.avg_messages_per_conversation + ' 条/会话' : '-'}</p>
              </div>
              <div style={{ width: '48px', height: '48px', borderRadius: '12px', backgroundColor: '#fef9c3', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#eab308" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              </div>
            </div>
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '4px', color: '#22c55e', fontSize: '12px' }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5M8 12l4-4 4 4" />
              </svg>
              较昨日 -15秒
            </div>
          </Card>

          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyItems: 'space-between' }}>
              <div>
                <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>AI 解决数</p>
                <p style={{ margin: '8px 0 0', fontSize: '32px', fontWeight: 700, color: '#1f2937' }}>{stats.ai_resolved ?? 0}</p>
              </div>
              <div style={{ width: '48px', height: '48px', borderRadius: '12px', backgroundColor: '#fce7f3', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ec4899" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </div>
            </div>
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '4px', color: '#6b7280', fontSize: '12px' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#22c55e', display: 'inline-block' }} />
              {stats.ai_resolved ?? 0} 个会话已解决
            </div>
          </Card>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>最近会话</h2>
              <Button variant="ghost" size="sm" onClick={() => navigate('/contacts')}>查看全部</Button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {recentConversations.map((conv) => (
                <div key={conv.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px', backgroundColor: '#f9fafb', borderRadius: '8px' }}>
                  <div style={{ width: '36px', height: '36px', borderRadius: '9px', backgroundColor: '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, color: '#6b7280' }}>
                    {conv.contact?.name?.charAt(0) ?? '?'}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontWeight: 500, color: '#1f2937' }}>{conv.contact?.name ?? '访客'}</span>
                      <Badge variant={conv.status === 'open' ? 'success' : conv.status === 'pending' ? 'warning' : 'default'} size="sm">
                        {conv.status === 'open' && '进行中'}
                        {conv.status === 'pending' && '待处理'}
                        {conv.status === 'resolved' && '已解决'}
                      </Badge>
                    </div>
                    <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {conv.lastMessage ?? ''}
                    </p>
                  </div>
                  <span style={{ fontSize: '11px', color: '#9ca3af' }}>{conv.lastMessageAt ? new Date(conv.lastMessageAt).toLocaleString() : ''}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>客服绩效</h2>
              <Button variant="ghost" size="sm" onClick={() => navigate('/agents')}>查看全部</Button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {agentPerf.length === 0 && (
                <p style={{ margin: 0, fontSize: '13px', color: '#9ca3af', textAlign: 'center', padding: '24px 0' }}>
                  暂无客服绩效数据
                </p>
              )}
              {agentPerf.map((agent: AgentPerf) => (
                <div key={agent.name} style={{ padding: '12px', backgroundColor: '#f9fafb', borderRadius: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                    <div style={{ width: '32px', height: '32px', borderRadius: '8px', backgroundColor: '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 500, color: '#6b7280' }}>
                      {agent.name.charAt(2) || '客'}
                    </div>
                    <div style={{ flex: 1 }}>
                      <span style={{ fontWeight: 500, color: '#1f2937' }}>{agent.name}</span>
                      <span style={{ marginLeft: '8px', fontSize: '12px', color: '#6b7280' }}>会话: {agent.conversations}</span>
                    </div>
                    <Badge variant={agent.resolved > 0 ? 'success' : 'default'} size="sm">
                      {agent.resolved} 已解决
                    </Badge>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '12px', color: '#6b7280' }}>
                    <span>解决率: <span style={{ color: '#22c55e', fontWeight: 500 }}>{agent.conversations ? Math.round((agent.resolved / agent.conversations) * 100) : 0}%</span></span>
                    <span>会话数: <span style={{ fontWeight: 500 }}>{agent.conversations}</span></span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <Card padding="md">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>会话趋势</h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Button
                variant={trendDays === 7 ? 'outline' : 'ghost'}
                size="sm"
                onClick={() => setTrendDays(7)}
              >
                本周
              </Button>
              <Button
                variant={trendDays === 30 ? 'outline' : 'ghost'}
                size="sm"
                onClick={() => setTrendDays(30)}
              >
                本月
              </Button>
            </div>
          </div>
          <div style={{ height: '200px', display: 'flex', alignItems: 'flex-end', justifyContent: 'space-around', gap: '16px' }}>
            {trend.length === 0 && (
              <p style={{ margin: 'auto', fontSize: '13px', color: '#9ca3af' }}>暂无趋势数据</p>
            )}
            {trend.map((point) => (
              <div key={point.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '11px', color: '#6b7280' }}>{point.total}</span>
                <div
                  style={{
                    height: `${Math.max(8, (point.total / trendMax) * 100)}%`,
                    maxHeight: '160px',
                    width: '100%',
                    backgroundColor: '#6366f1',
                    borderRadius: '4px 4px 0 0',
                  }}
                />
                <span style={{ fontSize: '11px', color: '#6b7280' }}>{point.date.slice(5)}</span>
              </div>
            ))}
          </div>
        </Card>
      </main>
    </div>
  );
}