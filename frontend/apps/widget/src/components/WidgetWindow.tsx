import { useRef, useEffect, useState, type KeyboardEvent } from 'react';
import type { WidgetConfig } from '@ai-cs/shared/types';
import { useChat } from '@ai-cs/shared/hooks';
import { fetchHandoffMessages } from '@ai-cs/shared/api';

interface WidgetWindowProps {
  config: WidgetConfig;
  suggestions?: string[];
  onClose: () => void;
}

const DEFAULT_SUGGESTIONS = [
  '你们的营业时间是什么？',
  '怎么退货？',
  '怎么联系人工客服？',
];

/** 腾讯云 Kiki 风格：全高右侧助手窗口 + 旋转渐变边框 */
export function WidgetWindow({ config, suggestions = DEFAULT_SUGGESTIONS, onClose }: WidgetWindowProps) {
  const {
    messages,
    isTyping,
    sendMessage,
    addMessage,
    conversationId,
    capabilityToken,
    handoffActive,
    chatwootConversationId: chatwootConvId,
    sessionErrorCode,
    startNewConversation,
  } = useChat({ apiUrl: config.apiUrl, siteToken: config.siteToken });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [inputValue, setInputValue] = useState('');
  const [focused, setFocused] = useState(false);
  const recoveryBlocked = sessionErrorCode === 'HANDOFF_SESSION_NOT_RESTORABLE';

  // 最新的消息列表引用（避免轮询闭包拿到旧数据）
  const messagesRef = useRef(messages);
  useEffect(() => { messagesRef.current = messages; }, [messages]);

  // 转人工后 WebSocket 实时接收客服回复（失败时回退轮询）
  const shownRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!handoffActive || !chatwootConvId || !capabilityToken) return;

    // 去重后追加客服回复到消息列表（WebSocket 与轮询共用）
    const appendAgentReply = (m: { id?: number | string; content?: string; senderName?: string; createdAt?: string }) => {
      if (!m?.content) return;
      const key = `${m.id || ''}:${m.content}`;
      if (shownRef.current.has(key)) return;
      const exists = (messagesRef.current || []).some(
        (x) => x.senderType === 'agent' && x.content === m.content
      );
      if (!exists) {
        addMessage({
          id: m.id ? `cw-${m.id}` : `agent-${Date.now()}`,
          conversationId,
          senderType: 'agent',
          senderName: m.senderName || '人工客服',
          contentType: 'text',
          content: m.content,
          status: 'delivered',
          createdAt: m.createdAt || new Date().toISOString(),
        });
      }
      shownRef.current.add(key);
    };

    // WebSocket 实时推送
    let ws: WebSocket | null = null;
    try {
      const websocketBase = config.apiUrl.replace(/^http/, 'ws').replace(/\/$/, '');
      ws = new WebSocket(
        `${websocketBase}/ws/widget?conversation_id=${encodeURIComponent(chatwootConvId)}`
      );
      ws.onopen = () => {
        ws?.send(JSON.stringify({ type: 'auth', token: capabilityToken }));
      };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'agent_reply') appendAgentReply(data.message);
        } catch { /* 忽略解析错误 */ }
      };
    } catch { /* WebSocket 不可用，回退轮询 */ }

    // 轮询兜底（WebSocket 失败时仍能收到回复）
    const poll = async () => {
      try {
        const res = await fetchHandoffMessages(conversationId, capabilityToken, config.apiUrl);
        if (!res || !res.handoff) return;
        for (const m of res.messages || []) {
          if (m.senderType !== 'agent') continue; // 只追加客服回复
          appendAgentReply(m);
        }
      } catch {
        /* 轮询失败忽略，下次重试 */
      }
    };

    poll();
    const timer = setInterval(poll, 4000);
    return () => {
      clearInterval(timer);
      if (ws) ws.close();
    };
  }, [handoffActive, chatwootConvId, capabilityToken, conversationId, addMessage, config.apiUrl]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSend = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isTyping || recoveryBlocked) return;
    sendMessage(trimmed);
    setInputValue('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(inputValue);
    }
  };

  return (
    <div
      className="kiki-window"
      style={{
        [config.position === 'left' ? 'left' : 'right']: '24px',
        zIndex: config.zIndex,
      }}
    >
      {/* 模糊光晕 */}
      <div className="kiki-aura" />
      {/* 旋转渐变边框 */}
      <div className="kiki-border" />

      {/* 面板 */}
      <div className="kiki-panel">
        {/* 头部 */}
        <div className="kiki-header">
          <div className="kiki-header-avatar">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="4" y="8" width="16" height="12" rx="3" />
              <path d="M12 4v4" />
              <circle cx="12" cy="2.8" r="1.2" fill="currentColor" stroke="none" />
              <path d="M2 13h2M20 13h2" />
              <line x1="8" y1="13" x2="8" y2="15.5" />
              <line x1="16" y1="13" x2="16" y2="15.5" />
            </svg>
          </div>
          <div>
            <h3 className="kiki-header-title">{config.brandName}</h3>
            <p className="kiki-header-sub">智能助手 · 7×24 小时在线</p>
          </div>
          <button className="kiki-header-close" onClick={onClose} aria-label="关闭">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* 消息区 */}
        <div className="kiki-messages">
          {recoveryBlocked ? (
            <div className="kiki-empty" role="alert">
              <h4 className="kiki-empty-title">原人工会话无法安全恢复</h4>
              <p className="kiki-empty-desc">
                这是升级前建立的会话，缺少访客绑定信息。请确认后开始新的会话。
              </p>
              <div className="kiki-pills">
                <button className="kiki-pill" onClick={() => void startNewConversation()}>
                  开始新会话
                </button>
              </div>
            </div>
          ) : messages.length === 0 && !isTyping ? (
            /* 空状态：欢迎 + 推荐问题 */
            <div className="kiki-empty">
              <div className="kiki-empty-hero">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="34"
                  height="34"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect x="4" y="8" width="16" height="12" rx="3" />
                  <path d="M12 4v4" />
                  <circle cx="12" cy="2.8" r="1.2" fill="currentColor" stroke="none" />
                  <path d="M2 13h2M20 13h2" />
                  <line x1="8" y1="13" x2="8" y2="15.5" />
                  <line x1="16" y1="13" x2="16" y2="15.5" />
                </svg>
              </div>
              <h4 className="kiki-empty-title">{config.welcomeMessage}</h4>
              <p className="kiki-empty-desc">您可以向我咨询产品或服务问题，也可以试试下面的常见问题：</p>
              <div className="kiki-pills">
                {suggestions.map((s) => (
                  <button key={s} className="kiki-pill" onClick={() => handleSend(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((message) => {
                const isUser = message.senderType === 'user';
                const isAI = message.senderType === 'ai';
                return (
                  <div key={message.id} className={`kiki-row ${isUser ? 'kiki-row--user' : ''}`}>
                    {!isUser && (
                      <div className="kiki-bubble-avatar">
                        {message.senderName?.charAt(0) || 'A'}
                      </div>
                    )}
                    <div>
                      <div className={`kiki-bubble ${isUser ? 'kiki-bubble--user' : 'kiki-bubble--assistant'}`}>
                        {!isUser && <span className="kiki-bubble-name">{message.senderName}</span>}
                        <p className="kiki-bubble-text">{message.content}</p>
                        {isAI && message.handoff?.ok && (
                          <div className="kiki-handoff-badge">
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              width="14"
                              height="14"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                              <circle cx="9" cy="7" r="4" />
                              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                            </svg>
                            已转接人工客服，请稍候
                          </div>
                        )}
                        {isAI && message.confidence !== undefined && (
                          <div className="kiki-sources">
                            置信度 {Math.round(message.confidence * 100)}%
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              {isTyping && (
                <div className="kiki-row">
                  <div className="kiki-bubble-avatar">A</div>
                  <div className="kiki-bubble kiki-bubble--assistant">
                    <div className="kiki-typing">
                      <span /><span /><span />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* 输入区 */}
        <div className="kiki-input-area">
          <div className={`kiki-input-box ${focused ? 'kiki-input-box--focused' : ''}`}>
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              placeholder="输入消息，Enter 发送..."
              disabled={isTyping || recoveryBlocked}
              rows={1}
            />
            <button
              className="kiki-send-btn"
              onClick={() => handleSend(inputValue)}
              disabled={!inputValue.trim() || isTyping || recoveryBlocked}
              aria-label="发送"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
