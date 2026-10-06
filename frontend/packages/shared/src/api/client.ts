import type {
  AdminContact,
  Agent,
  AIKnowledgeResponse,
  AIStats,
  BridgeChatRequest,
  BridgeChatResponse,
  Conversation,
  ConversationDetailResponse,
  ConversationListResponse,
  ConversationStatus,
  KnowledgeJob,
  KnowledgeJobListResponse,
  Message,
  TrendPoint,
} from '../types';

interface ImportMetaWithEnv {
  env?: {
    VITE_BRIDGE_API_BASE?: string;
  };
}

const env = (import.meta as unknown as ImportMetaWithEnv).env;
const API_BASE = (env?.VITE_BRIDGE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

export function getBridgeWebSocketUrl(path: string): string {
  const httpBase = API_BASE || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000');
  return `${httpBase.replace(/^http/, 'ws')}${path.startsWith('/') ? path : `/${path}`}`;
}

let authToken: string | null = null;
const authTokenListeners = new Set<(token: string | null) => void>();

export interface AuthResponse {
  token: string;
  user: {
    id: string;
    username: string;
    role: 'agent' | 'admin';
  };
  expires_in: number;
}

export type AuthenticatedRole = 'agent' | 'admin';

export interface SetupStatus {
  initialized: boolean;
  setup_token_configured: boolean;
  agent_credentials_configured: boolean;
  version: number;
}

export interface InitializeSetupRequest {
  site: { name: string; brand_color: string; locale: 'zh-CN' | 'en-US' };
  model: { provider: string; api_base: string; api_key: string; model: string };
  chatwoot: { base_url: string; api_token: string; account_id: string; inbox_id: number };
  admin: { username: string; password: string };
  agent: { username: string; password: string };
  ai_rules: {
    welcome_message: string;
    system_prompt: string;
    confidence_threshold: number;
    handoff_keywords: string[];
  };
  allowed_origins: string[];
  verify_connections: boolean;
}

export function fetchSetupStatus(): Promise<SetupStatus> {
  return request('/api/setup/status', {}, { useAccessToken: false, retryAuth: false });
}

export function initializeSetup(payload: InitializeSetupRequest, setupToken: string): Promise<{ initialized: boolean; initialized_at: string }> {
  return request('/api/setup/initialize', {
    method: 'POST',
    headers: { 'X-Setup-Token': setupToken },
    body: JSON.stringify(payload),
  }, { useAccessToken: false, retryAuth: false });
}

export function setAuthToken(token: string | null): void {
  authToken = token;
  authTokenListeners.forEach((listener) => listener(token));
}

export function getAuthToken(): string | null {
  return authToken;
}

export function subscribeAuthToken(listener: (token: string | null) => void): () => void {
  authTokenListeners.add(listener);
  return () => authTokenListeners.delete(listener);
}

interface RequestOptions {
  isFormData?: boolean;
  useAccessToken?: boolean;
  capabilityToken?: string | null;
  retryAuth?: boolean;
  baseUrl?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function createHeaders(
  extraHeaders?: HeadersInit,
  options: RequestOptions = {},
): Headers {
  const headers = new Headers(extraHeaders);

  // FormData 由浏览器自动设置 Content-Type（含 boundary），不能手动指定
  if (!options.isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const token = options.capabilityToken || (options.useAccessToken !== false ? authToken : null);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  return headers;
}

let activeAuthRole: AuthenticatedRole | null = null;
let refreshPromise: { role: AuthenticatedRole; promise: Promise<AuthResponse> } | null = null;

export function setAuthRole(role: AuthenticatedRole): void {
  if (activeAuthRole !== role) {
    activeAuthRole = role;
    setAuthToken(null);
  }
}

export async function refreshSession(role: AuthenticatedRole): Promise<AuthResponse> {
  setAuthRole(role);
  if (!refreshPromise || refreshPromise.role !== role) {
    const promise = request<AuthResponse>(
      `/api/auth/refresh?role=${encodeURIComponent(role)}`,
      { method: 'POST' },
      { useAccessToken: false, retryAuth: false },
    )
      .then((data) => {
        setAuthToken(data.token);
        return data;
      })
      .catch((error) => {
        setAuthToken(null);
        throw error;
      })
      .finally(() => {
        if (refreshPromise?.promise === promise) refreshPromise = null;
      });
    refreshPromise = { role, promise };
  }
  return refreshPromise.promise;
}

export function restoreSession(role: AuthenticatedRole): Promise<AuthResponse> {
  return refreshSession(role);
}

async function request<T>(
  url: string,
  options: RequestInit = {},
  requestOptions: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${(requestOptions.baseUrl || API_BASE).replace(/\/$/, '')}${url}`, {
    ...options,
    credentials: 'include',
    headers: createHeaders(options.headers, requestOptions),
  });

  if (!response.ok) {
    if (
      response.status === 401
      && requestOptions.useAccessToken !== false
      && requestOptions.retryAuth !== false
    ) {
      if (!activeAuthRole) {
        throw new ApiError('未配置认证角色', 401, 'AUTH_ROLE_NOT_CONFIGURED');
      }
      await refreshSession(activeAuthRole);
      return request<T>(url, options, { ...requestOptions, retryAuth: false });
    }
    const errorData = await response.json().catch(() => ({}));
    const detail = errorData.detail;
    const code = detail && typeof detail === 'object' && typeof detail.code === 'string'
      ? detail.code
      : undefined;
    const message = typeof detail === 'string'
      ? detail
      : errorData.message || code || `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, code);
  }

  return response.json() as Promise<T>;
}

export async function sendBridgeMessage({
  message,
  conversationId,
  userId,
  capabilityToken,
  apiUrl,
}: BridgeChatRequest): Promise<BridgeChatResponse> {
  return request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      user_id: userId,
    }),
  }, { useAccessToken: false, capabilityToken, baseUrl: apiUrl });
}

export async function fetchHandoffMessages(conversationId: string, capabilityToken: string, apiUrl?: string): Promise<any> {
  return request(
    `/api/chat/handoff?conversation_id=${encodeURIComponent(conversationId)}`,
    {},
    { useAccessToken: false, capabilityToken, baseUrl: apiUrl },
  );
}

export interface WidgetPublicConfig {
  brandName: string;
  welcomeMessage: string;
  themeColor: string;
  locale: 'zh-CN' | 'en-US';
  theme: 'light' | 'dark';
  position: 'left' | 'right';
}

export async function fetchWidgetPublicConfig(apiUrl: string, siteToken: string): Promise<WidgetPublicConfig> {
  return request('/api/widget/config', {
    headers: { 'X-Site-Token': siteToken },
  }, { useAccessToken: false, retryAuth: false, baseUrl: apiUrl });
}

export interface WidgetSessionResponse {
  capability_token: string;
  expires_at: number;
  handoff: boolean;
  chatwoot_conversation_id: string | null;
}

export async function createWidgetSession(apiUrl: string, siteToken: string, conversationId: string, visitorId: string): Promise<WidgetSessionResponse> {
  return request('/api/widget/session', {
    method: 'POST',
    headers: { 'X-Site-Token': siteToken },
    body: JSON.stringify({ conversation_id: conversationId, visitor_id: visitorId }),
  }, { useAccessToken: false, retryAuth: false, baseUrl: apiUrl });
}

export function fetchWidgetSnippet(): Promise<{ snippet: string; asset_url: string; api_base: string }> {
  return request('/api/widget/snippet');
}

export async function updateAgentStatus(username: string, status: string): Promise<any> {
  return request('/api/agent/status', {
    method: 'PUT',
    body: JSON.stringify({ username, status }),
  });
}

export async function transferAgentConversation(
  conversationId: string,
  assigneeId: number,
  note?: string
): Promise<Conversation> {
  const data = await request<{ conversation: Conversation }>(
    `/api/agent/conversations/${conversationId}/transfer`,
    {
      method: 'POST',
      body: JSON.stringify({ assignee_id: assigneeId, note: note || '' }),
    }
  );
  return data.conversation;
}

export function getOrCreateVisitorId(scope: string): string {
  const key = `ai-cs:${scope}:visitor-id`;
  const existing = localStorage.getItem(key);
  if (existing) return existing;

  const id =
    typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  localStorage.setItem(key, id);
  return id;
}

export function resetVisitorId(scope: string): string {
  localStorage.removeItem(`ai-cs:${scope}:visitor-id`);
  return getOrCreateVisitorId(scope);
}

export async function fetchAgentConversations(status = 'open'): Promise<ConversationListResponse> {
  return request(`/api/agent/conversations?status=${encodeURIComponent(status)}`);
}

export async function fetchAgentConversation(conversationId: string): Promise<ConversationDetailResponse> {
  return request(`/api/agent/conversations/${conversationId}`);
}

export async function fetchAgentUsers(): Promise<Agent[]> {
  const data = await request<{ agents: Agent[] }>('/api/agent/agents');
  return data.agents;
}

export async function sendAgentReply(conversationId: string, content: string): Promise<Message> {
  const data = await request<{ message: Message }>(`/api/agent/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
  return data.message;
}

export async function assignAgentConversation(
  conversationId: string,
  assigneeId: number | null
): Promise<Conversation> {
  const data = await request<{ conversation: Conversation }>(
    `/api/agent/conversations/${conversationId}/assignment`,
    {
      method: 'PATCH',
      body: JSON.stringify({ assignee_id: assigneeId }),
    }
  );
  return data.conversation;
}

export async function updateAgentConversationLabels(
  conversationId: string,
  labels: string[]
): Promise<Conversation> {
  const data = await request<{ conversation: Conversation }>(
    `/api/agent/conversations/${conversationId}/labels`,
    {
      method: 'PATCH',
      body: JSON.stringify({ labels }),
    }
  );
  return data.conversation;
}

export async function updateAgentConversationStatus(
  conversationId: string,
  status: ConversationStatus
): Promise<Conversation> {
  const data = await request<{ conversation: Conversation }>(
    `/api/agent/conversations/${conversationId}/status`,
    {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }
  );
  return data.conversation;
}

export async function fetchDashboardMetrics(): Promise<any> {
  return request('/api/admin/metrics');
}

export async function fetchAnalyticsSummary(
  startDate?: string,
  endDate?: string
): Promise<Record<string, unknown>> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const qs = params.toString();
  return request(`/api/conversations/analytics/summary${qs ? `?${qs}` : ''}`);
}

export async function login(username: string, password: string, role: AuthenticatedRole): Promise<AuthResponse> {
  setAuthRole(role);
  const response = await request<AuthResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password, role }),
  }, { useAccessToken: false });
  setAuthToken(response.token);
  return response;
}

export async function logout(role: AuthenticatedRole): Promise<void> {
  setAuthRole(role);
  try {
    await request(`/api/auth/logout?role=${encodeURIComponent(role)}`, {
      method: 'POST',
    }, { useAccessToken: false, retryAuth: false });
  } finally {
    setAuthToken(null);
  }
}

export interface AgentCredentialStatus {
  username: string;
  configured: boolean;
}

export function fetchAgentCredentials(): Promise<AgentCredentialStatus> {
  return request('/api/admin/agent-credentials');
}

export function updateAgentCredentials(
  username: string,
  password: string,
): Promise<AgentCredentialStatus> {
  return request('/api/admin/agent-credentials', {
    method: 'PUT',
    body: JSON.stringify({ username, password }),
  });
}

export async function fetchKnowledgeList(): Promise<any> {
  return request('/api/knowledge');
}

export async function createKnowledgeItem(data: any): Promise<any> {
  return request('/api/knowledge', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateKnowledgeItem(id: string, data: any): Promise<any> {
  return request(`/api/knowledge/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteKnowledgeItem(id: string): Promise<void> {
  await request(`/api/knowledge/${id}`, {
    method: 'DELETE',
  });
}

/* —— 管理后台（Admin 5175）—— */

export async function fetchContacts(): Promise<{ contacts: AdminContact[] }> {
  return request('/api/admin/contacts');
}

export async function fetchConversationTrend(days = 7): Promise<{ points: TrendPoint[] }> {
  return request(`/api/conversations/analytics/trend?days=${days}`);
}

export async function fetchConfig(): Promise<Record<string, any>> {
  return request('/api/config');
}

export async function updateConfigKey(key: string, value: any): Promise<{ status: string; key: string; value: any }> {
  return request('/api/config', {
    method: 'PUT',
    body: JSON.stringify({ key, value }),
  });
}

export async function updateConfigBatch(config: Record<string, any>): Promise<{ status: string; updated: number }> {
  return request('/api/config/batch', {
    method: 'POST',
    body: JSON.stringify({ config }),
  });
}

/* —— AI 管理 —— */

export async function fetchAIStats(): Promise<AIStats> {
  return request('/api/ai/stats');
}

export async function fetchAIKnowledge(limit = 50, offset = 0): Promise<AIKnowledgeResponse> {
  return request(`/api/ai/knowledge?limit=${limit}&offset=${offset}`);
}

export async function uploadAIKnowledge(file: File): Promise<{
  success: boolean;
  filename: string;
  documentsAdded: number;
  message: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  return request('/api/ai/knowledge/upload', {
    method: 'POST',
    body: formData,
  }, { isFormData: true });
}

interface KnowledgeJobPayload {
  id: string;
  filename: string;
  file_hash: string;
  source_id: string;
  ingestion_id: string;
  status: KnowledgeJob['status'];
  progress: number;
  documents_total: number;
  documents_indexed: number;
  error?: string | null;
  duplicate_of?: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
}

function normalizeKnowledgeJob(job: KnowledgeJobPayload): KnowledgeJob {
  return {
    id: job.id,
    filename: job.filename,
    fileHash: job.file_hash,
    sourceId: job.source_id,
    ingestionId: job.ingestion_id,
    status: job.status,
    progress: job.progress,
    documentsTotal: job.documents_total,
    documentsIndexed: job.documents_indexed,
    error: job.error,
    duplicateOf: job.duplicate_of,
    attempts: job.attempts,
    createdAt: job.created_at,
    updatedAt: job.updated_at,
  };
}

export async function uploadKnowledgeJob(file: File): Promise<{ job: KnowledgeJob }> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await request<{ job: KnowledgeJobPayload }>('/api/knowledge/import', {
    method: 'POST',
    body: formData,
  }, { isFormData: true });
  return { job: normalizeKnowledgeJob(response.job) };
}

export async function fetchKnowledgeJobs(limit = 50): Promise<KnowledgeJobListResponse> {
  const response = await request<{ items: KnowledgeJobPayload[]; total: number }>(`/api/knowledge/jobs?limit=${limit}`);
  return { items: response.items.map(normalizeKnowledgeJob), total: response.total };
}

export async function fetchKnowledgeJob(jobId: string): Promise<KnowledgeJob> {
  return normalizeKnowledgeJob(await request<KnowledgeJobPayload>(`/api/knowledge/jobs/${encodeURIComponent(jobId)}`));
}

export async function retryKnowledgeJob(jobId: string): Promise<{ job: KnowledgeJob }> {
  const response = await request<{ job: KnowledgeJobPayload }>(`/api/knowledge/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  });
  return { job: normalizeKnowledgeJob(response.job) };
}

export async function reloadAIKnowledge(): Promise<{ success: boolean; totalDocuments: number; message: string }> {
  return request('/api/ai/knowledge/reload', {
    method: 'POST',
  });
}

export async function testAIChat(message: string): Promise<{
  reply: string;
  confidence: number;
  intent: string;
  sources: unknown;
  message: string;
}> {
  return request('/api/ai/test', {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

export async function updateAIConfig(cfg: {
  apiKey?: string;
  apiBase?: string;
  model?: string;
  topK?: number;
  similarityThreshold?: number;
}): Promise<{ success: boolean; message: string; config: Record<string, any> }> {
  return request('/api/ai/config', {
    method: 'PUT',
    body: JSON.stringify(cfg),
  });
}
