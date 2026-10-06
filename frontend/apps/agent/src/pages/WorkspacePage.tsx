import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { Badge } from '@ai-cs/shared/components';
import type { Conversation, ConversationStatus } from '@ai-cs/shared/types';
import { formatTime, truncateText, getPriorityColor } from '@ai-cs/shared/utils';
import { fetchAgentConversations, getBridgeWebSocketUrl } from '@ai-cs/shared/api';
import { useWebSocket } from '@ai-cs/shared/hooks';

export function WorkspacePage() {
  const [statusFilter, setStatusFilter] = useState<ConversationStatus | 'all'>('all');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { logout, user, accessToken } = useAuth();
  const navigate = useNavigate();

  // 从 Bridge Service 加载真实会话（后端连接 Chatwoot）
  const loadConversations = useCallback(() => {
    return fetchAgentConversations(statusFilter === 'all' ? 'all' : statusFilter)
      .then((res) => setConversations(res.conversations ?? []))
      .catch(() => setError('加载会话失败，请检查 Bridge Service 是否运行'));
  }, [statusFilter]);

  useEffect(() => {
    setLoading(true);
    loadConversations().finally(() => setLoading(false));
  }, [loadConversations]);

  // WebSocket 实时推送：收到新消息时自动刷新会话列表
  useWebSocket({
    url: getBridgeWebSocketUrl('/ws/agent'),
    authToken: accessToken,
    onMessage: () => {
      loadConversations();
    },
  });

  const filteredConversations = conversations;

  const stats = {
    total: conversations.length,
    open: conversations.filter((c) => c.status === 'open').length,
    pending: conversations.filter((c) => c.status === 'pending').length,
    resolved: conversations.filter((c) => c.status === 'resolved').length,
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#f3f4f6' }}>
      <aside style={{ width: '280px', backgroundColor: '#ffffff', borderRight: '1px solid #e5e7eb', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid #e5e7eb' }}>
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

        <div style={{ padding: '16px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px' }}>
            <Card padding="sm">
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#1f2937' }}>{stats.total}</div>
              <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>总会话</div>
            </Card>
            <Card padding="sm">
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#22c55e' }}>{stats.open}</div>
              <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>进行中</div>
            </Card>
            <Card padding="sm">
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#eab308' }}>{stats.pending}</div>
              <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>待处理</div>
            </Card>
            <Card padding="sm">
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#6b7280' }}>{stats.resolved}</div>
              <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>已解决</div>
            </Card>
          </div>
        </div>

        <div style={{ padding: '0 16px', borderTop: '1px solid #e5e7eb' }}>
          <div style={{ fontSize: '13px', fontWeight: 600, color: '#374151', marginBottom: '8px', marginTop: '16px' }}>状态筛选</div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <Button
              variant={statusFilter === 'all' ? 'primary' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter('all')}
            >
              全部
            </Button>
            <Button
              variant={statusFilter === 'open' ? 'primary' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter('open')}
            >
              进行中
            </Button>
            <Button
              variant={statusFilter === 'pending' ? 'primary' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter('pending')}
            >
              待处理
            </Button>
            <Button
              variant={statusFilter === 'resolved' ? 'primary' : 'outline'}
              size="sm"
              onClick={() => setStatusFilter('resolved')}
            >
              已解决
            </Button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
          <div style={{ fontSize: '13px', fontWeight: 600, color: '#374151', marginBottom: '8px' }}>会话列表</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {loading && (
              <div style={{ textAlign: 'center', padding: '24px', color: '#6b7280' }}>加载中...</div>
            )}
            {error && (
              <div style={{ textAlign: 'center', padding: '24px', color: '#ef4444' }}>{error}</div>
            )}
            {!loading && !error && filteredConversations.length === 0 && (
              <div style={{ textAlign: 'center', padding: '24px', color: '#9ca3af' }}>暂无会话</div>
            )}
            {filteredConversations.map((conversation) => (
              <Link
                key={conversation.id}
                to={`/conversation/${conversation.id}`}
                style={{ textDecoration: 'none' }}
              >
                <Card padding="md" hover>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                    <div
                      style={{
                        width: '40px',
                        height: '40px',
                        borderRadius: '10px',
                        backgroundColor: '#f3f4f6',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#6b7280',
                        fontWeight: 600,
                        flexShrink: 0,
                      }}
                    >
                      {conversation.contact.name.charAt(0)}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <span style={{ fontWeight: 500, color: '#1f2937' }}>{conversation.contact.name}</span>
                        <Badge variant={conversation.status === 'open' ? 'success' : conversation.status === 'pending' ? 'warning' : 'default'} size="sm">
                          {conversation.status === 'open' && '进行中'}
                          {conversation.status === 'pending' && '待处理'}
                          {conversation.status === 'resolved' && '已解决'}
                          {conversation.status === 'snoozed' && '已暂停'}
                        </Badge>
                        {conversation.unreadCount > 0 && (
                          <span
                            style={{
                              backgroundColor: '#ef4444',
                              color: '#ffffff',
                              fontSize: '10px',
                              padding: '2px 6px',
                              borderRadius: '9999px',
                              fontWeight: 500,
                            }}
                          >
                            {conversation.unreadCount}
                          </span>
                        )}
                      </div>
                      <p style={{ margin: '4px 0', fontSize: '13px', color: '#6b7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {truncateText(conversation.lastMessage || '', 30)}
                      </p>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                        <span style={{ fontSize: '11px', color: '#9ca3af' }}>{formatTime(conversation.lastMessageAt || '')}</span>
                        {conversation.priority !== 'low' && (
                          <span
                            style={{
                              width: '8px',
                              height: '8px',
                              borderRadius: '50%',
                              backgroundColor: getPriorityColor(conversation.priority),
                            }}
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </div>

        <div style={{ padding: '16px', borderTop: '1px solid #e5e7eb' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '9px', backgroundColor: '#f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280', fontWeight: 600 }}>
              {user?.username?.charAt(0) || 'A'}
            </div>
            <div style={{ flex: 1 }}>
              <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>{user?.username}</p>
              <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#6b7280' }}>在线客服</p>
            </div>
            <Button variant="ghost" size="sm" onClick={handleLogout}>
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </Button>
          </div>
        </div>
      </aside>

      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', color: '#6b7280' }}>
          <div
            style={{
              width: '120px',
              height: '120px',
              borderRadius: '24px',
              backgroundColor: '#f3f4f6',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 24px',
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </div>
          <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 500, color: '#374151' }}>选择一个会话开始沟通</h2>
          <p style={{ margin: '8px 0 0', fontSize: '14px' }}>从左侧列表中选择一个会话，开始为客户提供帮助</p>
        </div>
      </main>
    </div>
  );
}
