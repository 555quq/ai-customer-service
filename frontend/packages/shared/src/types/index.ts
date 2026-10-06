export type SenderType = 'user' | 'ai' | 'agent' | 'system';

export type MessageStatus = 'sending' | 'sent' | 'delivered' | 'read' | 'failed';

export type MessageContentType = 'text' | 'image' | 'file' | 'card' | 'quick_replies';

export interface Message {
  id: string;
  conversationId: string;
  senderType: SenderType;
  senderName?: string;
  senderAvatar?: string;
  contentType: MessageContentType;
  content: string;
  confidence?: number;
  quickReplies?: QuickReply[];
  attachment?: Attachment;
  handoff?: {
    ok: boolean;
    conversation_id?: string;
    capability_token?: string;
  };
  status: MessageStatus;
  createdAt: string;
}

export interface QuickReply {
  id: string;
  label: string;
  value: string;
}

export interface Attachment {
  type: 'image' | 'file';
  url: string;
  name: string;
  size?: number;
  mimeType?: string;
}

export type ConversationStatus = 'open' | 'pending' | 'resolved' | 'snoozed';

export type ConversationPriority = 'low' | 'medium' | 'high' | 'urgent';

export interface Conversation {
  id: string;
  contact: Contact;
  status: ConversationStatus;
  priority: ConversationPriority;
  isHandedOff: boolean;
  assigneeId?: string;
  assigneeName?: string;
  labels: string[];
  lastMessage?: string;
  lastMessageAt?: string;
  unreadCount: number;
  createdAt: string;
}

export interface Contact {
  id: string;
  name: string;
  avatar?: string;
  email?: string;
  phone?: string;
  channel: 'web' | 'wechat' | 'wecom' | 'whatsapp' | 'app';
  attributes?: Record<string, string>;
}

export interface Agent {
  id: string;
  name: string;
  avatar?: string;
  status: 'online' | 'busy' | 'away' | 'offline';
  activeConversations: number;
  /** 后端 /api/agent/agents 返回的 Chatwoot 坐席 ID */
  chatwootId?: number;
  /** 后端 /api/agent/agents 返回的角色 */
  role?: string;
}

export interface DashboardMetrics {
  totalConversations: number;
  aiResolutionRate: number;
  avgResponseTime: number;
  satisfactionScore: number;
  handoffRate: number;
  trends: {
    conversations: number;
    aiResolution: number;
    responseTime: number;
    satisfaction: number;
  };
}

export interface TimeSeriesPoint {
  timestamp: string;
  value: number;
  label?: string;
}

export type Role = 'guest' | 'agent' | 'admin';

export interface User {
  id: string;
  username: string;
  role: Role;
  avatar?: string;
  email?: string;
  phone?: string;
  status?: 'online' | 'offline' | 'away';
}

export interface AuthState {
  isAuthenticated: boolean;
  role: Role;
  user?: User;
}

export interface WidgetConfig {
  apiUrl: string;
  siteToken?: string;
  locale?: 'zh-CN' | 'en-US';
  theme?: 'light' | 'dark';
  brandName?: string;
  welcomeMessage?: string;
  position?: 'left' | 'right';
  themeColor?: string;
  zIndex?: number;
}

export interface BridgeChatRequest {
  message: string;
  conversationId: string;
  userId: string;
  capabilityToken?: string | null;
  apiUrl?: string;
}

export interface BridgeChatResponse {
  reply: string;
  intent: string;
  confidence: number;
  conversation_id: string;
  response_time_ms: number;
  ok?: boolean;
  handoff?: {
    ok: boolean;
    conversation_id?: string;
    capability_token?: string;
  };
}

export interface ConversationListResponse {
  conversations: Conversation[];
  meta?: Record<string, number>;
}

export interface ConversationDetailResponse {
  conversation: Conversation;
  messages: Message[];
}

/* —— 管理后台 / AI 管理相关类型 —— */

export interface AIStats {
  totalDocuments: number;
  modelName: string;
  vectorDBStatus: string;
  lastUpdated: string;
  apiBase: string;
  topK: number;
  similarityThreshold: number;
}

export interface KnowledgeItem {
  id: string;
  text: string;
  source: string;
  category: string;
  score?: number;
}

export interface AIKnowledgeResponse {
  items: KnowledgeItem[];
  total: number;
  limit: number;
  offset: number;
}

export type KnowledgeJobStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface KnowledgeJob {
  id: string;
  filename: string;
  fileHash: string;
  sourceId: string;
  ingestionId: string;
  status: KnowledgeJobStatus;
  progress: number;
  documentsTotal: number;
  documentsIndexed: number;
  error?: string | null;
  duplicateOf?: string | null;
  attempts: number;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeJobListResponse {
  items: KnowledgeJob[];
  total: number;
}

export interface AdminContact {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  channel: string;
  lastActive?: string;
  conversationCount: number;
}

export interface TrendPoint {
  date: string;
  open: number;
  resolved: number;
  total: number;
}
