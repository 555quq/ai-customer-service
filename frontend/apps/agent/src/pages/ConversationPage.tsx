import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { useWebSocket } from '@ai-cs/shared/hooks';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { Badge } from '@ai-cs/shared/components';
import type { Message, Conversation, Agent } from '@ai-cs/shared/types';
import { formatTime } from '@ai-cs/shared/utils';
import { ChatBubble } from '@ai-cs/shared/components';
import { ChatInput } from '@ai-cs/shared/components';
import { ChatHeader } from '@ai-cs/shared/components';
import {
  fetchAgentConversation,
  fetchAgentUsers,
  getBridgeWebSocketUrl,
  sendAgentReply,
  assignAgentConversation,
  transferAgentConversation,
} from '@ai-cs/shared/api';

/** 客服会话详情页：真实数据 + 客服分配 + 实时回复 */
export function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user, accessToken } = useAuth();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [assigneeId, setAssigneeId] = useState<string>('');
  const [assigning, setAssigning] = useState(false);
  const [showTransfer, setShowTransfer] = useState(false);
  const [transferTo, setTransferTo] = useState('');
  const [transferNote, setTransferNote] = useState('');
  const [transferring, setTransferring] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isTyping = false;
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadDetail = useCallback(async () => {
    if (!id) return;
    try {
      const data = await fetchAgentConversation(id);
      setConversation(data.conversation);
      setMessages(data.messages || []);
      if (data.conversation.assigneeId) setAssigneeId(data.conversation.assigneeId);
      setError(null);
    } catch (e) {
      setError('无法加载会话详情');
    } finally {
      setLoading(false);
    }
  }, [id]);

  // 加载会话详情 + 客服列表
  useEffect(() => {
    loadDetail();
    fetchAgentUsers()
      .then(setAgents)
      .catch(() => setAgents([]));
  }, [loadDetail]);

  // 轮询新消息（访客在 widget 里发消息，客服这边实时看到）
  useEffect(() => {
    if (!id) return;
    const timer = setInterval(async () => {
      try {
        const data = await fetchAgentConversation(id);
        setConversation((prev) => ({ ...(prev || {}), ...data.conversation } as Conversation));
        setMessages((prev) => {
          const existing = new Map(prev.map((m) => [m.id, m]));
          for (const m of data.messages || []) existing.set(m.id, m);
          return Array.from(existing.values());
        });
      } catch {
        /* 轮询失败忽略 */
      }
    }, 5000);
    return () => clearInterval(timer);
  }, [id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // WebSocket 实时推送：当前会话有新访客消息时立即刷新
  useWebSocket({
    url: getBridgeWebSocketUrl('/ws/agent'),
    authToken: accessToken,
    onMessage: (raw) => {
      try {
        const data = typeof raw === 'string' ? JSON.parse(raw) : raw;
        if (data?.type === 'conversation_message' && String(data.conversation_id) === String(id)) {
          loadDetail();
        }
      } catch { /* 忽略 */ }
    },
  });

  const handleSendMessage = async (content: string) => {
    if (!content.trim() || !id || sending) return;
    setSending(true);
    try {
      const sent = await sendAgentReply(id, content.trim());
      setMessages((prev) => [...prev, sent]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          conversationId: id,
          senderType: 'system',
          contentType: 'text',
          content: '回复发送失败，请重试',
          status: 'failed',
          createdAt: new Date().toISOString(),
        } as Message,
      ]);
    } finally {
      setSending(false);
    }
  };

  const handleAssign = async () => {
    if (!id || assigning) return;
    setAssigning(true);
    try {
      // 未选择客服时传 null 表示取消分配
      await assignAgentConversation(id, assigneeId ? Number(assigneeId) : null);
      // 重新拉取详情，获取最新 assignee 信息
      await loadDetail();
    } catch (e) {
      setError('分配失败，请重试');
    } finally {
      setAssigning(false);
    }
  };

  const handleTransfer = async () => {
    if (!id || !transferTo || transferring) return;
    setTransferring(true);
    try {
      await transferAgentConversation(id, Number(transferTo), transferNote);
      setShowTransfer(false);
      setTransferNote('');
      await loadDetail();
    } catch (e) {
      setError('转接失败，请重试');
    } finally {
      setTransferring(false);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#6b7280' }}>
        加载中...
      </div>
    );
  }

  if (!conversation) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#6b7280', gap: '12px' }}>
        <p>{error || '会话不存在'}</p>
        <Button variant="outline" size="sm" onClick={() => navigate('/workspace')}>返回工作台</Button>
      </div>
    );
  }

  const currentAgent = agents.find((a) => String(a.id) === String(assigneeId));

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

        <div style={{ flex: 1, padding: '16px', overflowY: 'auto' }}>
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
              <div
                style={{
                  width: '40px', height: '40px', borderRadius: '10px', backgroundColor: '#f3f4f6',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280', fontWeight: 600,
                }}
              >
                {conversation.contact.name.charAt(0)}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontWeight: 500, color: '#1f2937' }}>{conversation.contact.name}</span>
                  <Badge variant={conversation.status === 'open' ? 'success' : conversation.status === 'pending' ? 'warning' : 'default'} size="sm">
                    {conversation.status === 'open' && '进行中'}
                    {conversation.status === 'pending' && '待处理'}
                    {conversation.status === 'resolved' && '已解决'}
                    {conversation.status === 'snoozed' && '已暂停'}
                  </Badge>
                </div>
                <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#6b7280' }}>
                  渠道: {conversation.contact.channel === 'web' && '网页'}
                  {conversation.contact.channel === 'wechat' && '微信'}
                  {conversation.contact.channel === 'app' && 'App'}
                </p>
              </div>
            </div>

            <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>
                <span>会话开始</span>
                <span>{formatTime(conversation.createdAt)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>
                <span>最后消息</span>
                <span>{conversation.lastMessageAt ? formatTime(conversation.lastMessageAt) : '-'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>
                <span>优先级</span>
                <span style={{ color: conversation.priority === 'high' ? '#ef4444' : conversation.priority === 'medium' ? '#eab308' : '#6b7280' }}>
                  {conversation.priority === 'high' && '高'}
                  {conversation.priority === 'medium' && '中'}
                  {conversation.priority === 'low' && '低'}
                </span>
              </div>

              {/* 客服分配 */}
              <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: '12px', marginTop: '8px' }}>
                <div style={{ fontSize: '12px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>客服分配</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <select
                    value={assigneeId}
                    onChange={(e) => setAssigneeId(e.target.value)}
                    style={{
                      flex: 1, padding: '6px 8px', borderRadius: '6px', border: '1px solid #d1d5db',
                      fontSize: '13px', color: '#1f2937', background: '#ffffff',
                    }}
                  >
                    <option value="">未分配</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                  <Button variant="outline" size="sm" onClick={handleAssign} disabled={assigning}>
                    {assigning ? '分配中' : '分配'}
                  </Button>
                </div>
                <p style={{ margin: '6px 0 0', fontSize: '12px', color: currentAgent ? '#059669' : '#9ca3af' }}>
                  当前客服: {conversation.assigneeName || currentAgent?.name || '未分配'}
                </p>
              </div>
            </div>

            {conversation.labels.length > 0 && (
              <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: '12px', marginTop: '8px' }}>
                <div style={{ fontSize: '12px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>标签</div>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  {conversation.labels.map((label) => (
                    <span key={label} style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '9999px', backgroundColor: '#e0e7ff', color: '#4338ca' }}>
                      {label}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </Card>
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
          </div>
        </div>
      </aside>

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: '#ffffff' }}>
        <ChatHeader
          contact={conversation.contact}
          isOnline={true}
          onClose={() => navigate('/workspace')}
        />

        <div style={{ flex: 1, overflowY: 'auto', padding: '24px', backgroundColor: '#f9fafb' }}>
          <div style={{ maxWidth: '800px', margin: '0 auto' }}>
            {error && (
              <div style={{ padding: '10px 14px', marginBottom: '12px', backgroundColor: '#fef2f2', color: '#b91c1c', borderRadius: '8px', fontSize: '13px' }}>
                {error}
              </div>
            )}
            {messages.map((message) => (
              <ChatBubble
                key={message.id}
                message={message}
                showAvatar={true}
              />
            ))}
            {isTyping && (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '16px' }}>
                <div
                  style={{
                    width: '36px', height: '36px', borderRadius: '9px', backgroundColor: '#f3f4f6',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280', fontWeight: 600, flexShrink: 0,
                  }}
                >
                  {conversation.contact.name.charAt(0)}
                </div>
                <div style={{ padding: '12px 16px', backgroundColor: '#ffffff', borderRadius: '0 12px 12px 12px', boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#9ca3af', animation: 'typing 1s infinite' }} />
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#9ca3af', animation: 'typing 1s infinite 0.2s' }} />
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#9ca3af', animation: 'typing 1s infinite 0.4s' }} />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <div style={{ padding: '8px 24px', borderTop: '1px solid #e5e7eb', backgroundColor: '#ffffff' }}>
          <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', gap: '8px' }}>
            <Button variant="outline" size="sm" onClick={() => setShowTransfer(true)}>
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 10v6M2 10l10-5 10 5-10 5z" />
              </svg>
              转接
            </Button>
            <Button variant="outline" size="sm">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
              </svg>
              标签
            </Button>
            <div style={{ flex: 1 }} />
          </div>
        </div>

        <div style={{ padding: '16px 24px', borderTop: '1px solid #e5e7eb', backgroundColor: '#ffffff' }}>
          <div style={{ maxWidth: '800px', margin: '0 auto' }}>
            <ChatInput onSend={handleSendMessage} disabled={sending} placeholder="输入回复消息..." />
          </div>
        </div>
      </main>

      {/* 转接弹窗 */}
      {showTransfer && (
        <div
          style={{
            position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
          onClick={() => setShowTransfer(false)}
        >
          <div
            style={{ backgroundColor: '#ffffff', borderRadius: '16px', padding: '24px', width: '360px', boxShadow: '0 20px 60px rgba(0,0,0,0.2)' }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>转接会话</h3>
            <label style={{ fontSize: '12px', color: '#374151', display: 'block', marginBottom: '6px' }}>转接给</label>
            <select
              value={transferTo}
              onChange={(e) => setTransferTo(e.target.value)}
              style={{
                width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid #d1d5db',
                fontSize: '14px', color: '#1f2937', background: '#fff', marginBottom: '12px',
              }}
            >
              <option value="">请选择客服</option>
              {agents
                .filter((a) => String(a.id) !== String(assigneeId))
                .map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
            </select>
            <label style={{ fontSize: '12px', color: '#374151', display: 'block', marginBottom: '6px' }}>备注（可选）</label>
            <textarea
              value={transferNote}
              onChange={(e) => setTransferNote(e.target.value)}
              placeholder="例如：用户要求优先处理"
              rows={3}
              style={{
                width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid #d1d5db',
                fontSize: '14px', color: '#1f2937', resize: 'none', marginBottom: '16px', fontFamily: 'inherit',
              }}
            />
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <Button variant="ghost" size="sm" onClick={() => setShowTransfer(false)}>取消</Button>
              <Button variant="primary" size="sm" onClick={handleTransfer} disabled={!transferTo || transferring}>
                {transferring ? '转接中...' : '确认转接'}
              </Button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes typing {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
