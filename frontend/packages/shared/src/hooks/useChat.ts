import { useState, useCallback, useRef, useEffect } from 'react';
import type { Message, MessageStatus } from '../types';
import {
  createWidgetSession,
  getOrCreateVisitorId,
  resetVisitorId,
  sendBridgeMessage,
  type WidgetSessionResponse,
} from '../api/client';
import { generateId } from '../utils';

interface UseChatOptions {
  initialMessages?: Message[];
  conversationId?: string;
  userId?: string;
  apiUrl?: string;
  siteToken?: string;
}

interface UseChatReturn {
  messages: Message[];
  isTyping: boolean;
  sendMessage: (content: string) => Promise<void>;
  addMessage: (message: Message) => void;
  updateMessageStatus: (messageId: string, status: MessageStatus) => void;
  clearMessages: () => void;
  conversationId: string;
  capabilityToken: string | null;
  handoffActive: boolean;
  chatwootConversationId: string | null;
  sessionErrorCode: string | null;
  startNewConversation: () => Promise<void>;
}

function getSessionErrorCode(error: unknown): string {
  if (error && typeof error === 'object' && 'code' in error) {
    const code = (error as { code?: unknown }).code;
    if (typeof code === 'string' && code) return code;
  }
  return 'WIDGET_SESSION_FAILED';
}

export function useChat({
  initialMessages = [],
  conversationId: externalConvId,
  userId: externalUserId,
  apiUrl,
  siteToken,
}: UseChatOptions = {}): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [isTyping, setIsTyping] = useState(false);
  const [capabilityToken, setCapabilityToken] = useState<string | null>(null);
  const [handoffActive, setHandoffActive] = useState(false);
  const [chatwootConversationId, setChatwootConversationId] = useState<string | null>(null);
  const [currentConversationId, setCurrentConversationId] = useState(
    externalConvId || getOrCreateVisitorId('conversation'),
  );
  const [sessionErrorCode, setSessionErrorCode] = useState<string | null>(null);
  const capabilityTokenRef = useRef<string | null>(null);
  const sessionPromiseRef = useRef<Promise<WidgetSessionResponse> | null>(null);
  const userIdRef = useRef<string>(externalUserId || getOrCreateVisitorId('chat'));
  const conversationIdRef = useRef<string>(currentConversationId);

  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const updateMessageStatus = useCallback((messageId: string, status: MessageStatus) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === messageId ? { ...msg, status } : msg))
    );
  }, []);

  const applySession = useCallback((session: WidgetSessionResponse) => {
    capabilityTokenRef.current = session.capability_token;
    setCapabilityToken(session.capability_token);
    setHandoffActive(session.handoff);
    setChatwootConversationId(session.chatwoot_conversation_id);
    setSessionErrorCode(null);
  }, []);

  const ensureSession = useCallback((): Promise<WidgetSessionResponse | null> => {
    if (capabilityTokenRef.current || !apiUrl || !siteToken) {
      return Promise.resolve(null);
    }
    if (sessionPromiseRef.current) return sessionPromiseRef.current;

    const pending = createWidgetSession(
      apiUrl,
      siteToken,
      conversationIdRef.current,
      userIdRef.current,
    )
      .then((session) => {
        applySession(session);
        return session;
      })
      .catch((error) => {
        setSessionErrorCode(getSessionErrorCode(error));
        throw error;
      })
      .finally(() => {
        if (sessionPromiseRef.current === pending) {
          sessionPromiseRef.current = null;
        }
      });
    sessionPromiseRef.current = pending;
    return pending;
  }, [apiUrl, siteToken, applySession]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    capabilityTokenRef.current = null;
    sessionPromiseRef.current = null;
    setCapabilityToken(null);
    setHandoffActive(false);
    setChatwootConversationId(null);
    setSessionErrorCode(null);
  }, []);

  const startNewConversation = useCallback(async () => {
    setMessages([]);
    capabilityTokenRef.current = null;
    sessionPromiseRef.current = null;
    setCapabilityToken(null);
    setHandoffActive(false);
    setChatwootConversationId(null);
    setSessionErrorCode(null);
    conversationIdRef.current = resetVisitorId('conversation');
    setCurrentConversationId(conversationIdRef.current);
    await ensureSession();
  }, [ensureSession]);

  const sendMessage = useCallback(async (content: string) => {
    const userMessage: Message = {
      id: generateId(),
      conversationId: conversationIdRef.current,
      senderType: 'user',
      senderName: '用户',
      contentType: 'text',
      content,
      status: 'sending',
      createdAt: new Date().toISOString(),
    };

    addMessage(userMessage);
    updateMessageStatus(userMessage.id, 'sent');
    setIsTyping(true);

    try {
      await ensureSession();
      const response = await sendBridgeMessage({
        message: content,
        conversationId: conversationIdRef.current,
        userId: userIdRef.current,
        capabilityToken: capabilityTokenRef.current,
        apiUrl,
      });

      if (response.handoff?.ok && response.handoff.capability_token) {
        capabilityTokenRef.current = response.handoff.capability_token;
        setCapabilityToken(response.handoff.capability_token);
        setHandoffActive(true);
        setChatwootConversationId(response.handoff.conversation_id || null);
      }

      addMessage({
        id: generateId(),
        conversationId: conversationIdRef.current,
        senderType: 'ai',
        senderName: 'AI助手',
        contentType: 'text',
        content: response.reply,
        confidence: response.confidence,
        handoff: response.handoff,
        status: 'delivered',
        createdAt: new Date().toISOString(),
      });
    } catch {
      addMessage({
        id: generateId(),
        conversationId: conversationIdRef.current,
        senderType: 'system',
        senderName: '系统',
        contentType: 'text',
        content: '抱歉，暂时无法回复，请稍后再试',
        status: 'delivered',
        createdAt: new Date().toISOString(),
      });
    } finally {
      setIsTyping(false);
    }
  }, [addMessage, updateMessageStatus, ensureSession, apiUrl]);

  useEffect(() => {
    void ensureSession().catch(() => undefined);
  }, [ensureSession]);

  useEffect(() => {
    if (externalConvId) {
      conversationIdRef.current = externalConvId;
      setCurrentConversationId(externalConvId);
    }
  }, [externalConvId]);

  useEffect(() => {
    if (externalUserId) userIdRef.current = externalUserId;
  }, [externalUserId]);

  return {
    messages,
    isTyping,
    sendMessage,
    addMessage,
    updateMessageStatus,
    clearMessages,
    conversationId: currentConversationId,
    capabilityToken,
    handoffActive,
    chatwootConversationId,
    sessionErrorCode,
    startNewConversation,
  };
}
