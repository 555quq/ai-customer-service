import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';
import { Badge } from '@ai-cs/shared/components';
import {
  fetchAIStats,
  fetchAIKnowledge,
  fetchKnowledgeJobs,
  retryKnowledgeJob,
  uploadKnowledgeJob,
  reloadAIKnowledge,
  testAIChat,
  updateAIConfig,
} from '@ai-cs/shared/api';
import type { AIStats, KnowledgeItem, KnowledgeJob } from '@ai-cs/shared/types';

const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: 'layout-dashboard' },
  { path: '/agents', label: '客服管理', icon: 'users' },
  { path: '/contacts', label: '客户管理', icon: 'user' },
  { path: '/ai', label: 'AI管理', icon: 'bot' },
  { path: '/settings', label: '系统设置', icon: 'settings' },
];

/** 服务商配置：URL → 该服务商可用模型列表 */
interface Provider {
  name: string;
  apiBase: string;
  models: { value: string; label: string }[];
}

const PROVIDERS: Provider[] = [
  {
    name: 'OpenAI',
    apiBase: 'https://api.openai.com/v1',
    models: [
      { value: 'gpt-4o', label: 'GPT-4o' },
      { value: 'gpt-4o-mini', label: 'GPT-4o mini' },
      { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
      { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
    ],
  },
  {
    name: 'DeepSeek',
    apiBase: 'https://api.deepseek.com/v1',
    models: [
      { value: 'deepseek-chat', label: 'DeepSeek Chat (V3)' },
      { value: 'deepseek-reasoner', label: 'DeepSeek Reasoner (R1)' },
    ],
  },
  {
    name: '通义千问',
    apiBase: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: [
      { value: 'qwen-turbo', label: '通义千问 Turbo' },
      { value: 'qwen-plus', label: '通义千问 Plus' },
      { value: 'qwen-max', label: '通义千问 Max' },
    ],
  },
  {
    name: 'Moonshot (Kimi)',
    apiBase: 'https://api.moonshot.cn/v1',
    models: [
      { value: 'moonshot-v1-8k', label: 'Moonshot v1 8K' },
      { value: 'moonshot-v1-32k', label: 'Moonshot v1 32K' },
      { value: 'moonshot-v1-128k', label: 'Moonshot v1 128K' },
    ],
  },
  {
    name: '智谱 GLM',
    apiBase: 'https://open.bigmodel.cn/api/paas/v4',
    models: [
      { value: 'glm-4', label: 'GLM-4' },
      { value: 'glm-4-flash', label: 'GLM-4 Flash' },
    ],
  },
  {
    name: '本地 Ollama',
    apiBase: 'http://localhost:11434/v1',
    models: [
      { value: 'llama3', label: 'Llama 3' },
      { value: 'qwen2', label: 'Qwen 2' },
    ],
  },
];

function findProvider(apiBase: string): Provider | undefined {
  return PROVIDERS.find((p) => p.apiBase === apiBase);
}

type TabKey = 'knowledge' | 'config' | 'test';

export function AIManagementPage() {
  const [activeNav, setActiveNav] = useState('ai');
  const [activeTab, setActiveTab] = useState<TabKey>('knowledge');
  const [aiStats, setAIStats] = useState<AIStats | null>(null);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [knowledgeJobs, setKnowledgeJobs] = useState<KnowledgeJob[]>([]);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState('');

  // 测试对话
  const [testMessage, setTestMessage] = useState('');
  const [testResponse, setTestResponse] = useState('');
  const [testing, setTesting] = useState(false);

  // 模型配置
  const [modelConfig, setModelConfig] = useState({
    apiKey: '',
    apiBase: 'https://api.openai.com/v1',
    model: 'gpt-3.5-turbo',
    topK: 3,
    similarityThreshold: 0.7,
  });

  const { user, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    loadAIStats();
  }, []);

  useEffect(() => {
    if (activeTab === 'knowledge') {
      loadKnowledge();
      loadKnowledgeJobs();
    }
  }, [activeTab]);

  const hasActiveJobs = knowledgeJobs.some((job) => job.status === 'pending' || job.status === 'processing');

  useEffect(() => {
    if (activeTab !== 'knowledge' || !hasActiveJobs) return;
    const timer = window.setInterval(async () => {
      try {
        const data = await fetchKnowledgeJobs(20);
        setKnowledgeJobs(data.items);
        if (!data.items.some((job) => job.status === 'pending' || job.status === 'processing')) {
          loadKnowledge();
          loadAIStats();
        }
      } catch {
        // 保留当前任务状态，下次轮询继续尝试。
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeTab, hasActiveJobs]);

  /** 用后端统计预填模型配置（apiBase/model/topK/阈值来自实际运行参数） */
  const loadAIStats = async () => {
    try {
      const data = await fetchAIStats();
      setAIStats(data);
      if (data.apiBase) {
        setModelConfig((prev) => ({
          ...prev,
          apiBase: data.apiBase,
          model: data.modelName || prev.model,
          topK: data.topK ?? prev.topK,
          similarityThreshold: data.similarityThreshold ?? prev.similarityThreshold,
        }));
      }
    } catch {
      // 忽略统计加载失败
    }
  };

  const loadKnowledge = async () => {
    setLoading(true);
    try {
      const data = await fetchAIKnowledge(100, 0);
      setKnowledgeItems(data.items ?? []);
    } catch {
      setKnowledgeItems([]);
    } finally {
      setLoading(false);
    }
  };

  const loadKnowledgeJobs = async () => {
    try {
      const data = await fetchKnowledgeJobs(20);
      setKnowledgeJobs(data.items);
    } catch {
      setKnowledgeJobs([]);
    }
  };

  const handleFileUpload = async () => {
    if (uploadFiles.length === 0) return;
    setUploading(true);
    setNotice('');
    try {
      const results = await Promise.allSettled(uploadFiles.map(uploadKnowledgeJob));
      const queued = results
        .filter((result): result is PromiseFulfilledResult<{ job: KnowledgeJob }> => result.status === 'fulfilled')
        .map((result) => result.value.job);
      setKnowledgeJobs((current) => [...queued, ...current.filter((job) => !queued.some((item) => item.id === job.id))]);
      setNotice(`已提交 ${queued.length} 个导入任务${queued.length < uploadFiles.length ? `，${uploadFiles.length - queued.length} 个提交失败` : ''}`);
      setUploadFiles([]);
    } catch {
      setNotice('提交失败，请检查文件格式');
    } finally {
      setUploading(false);
    }
  };

  const handleRetryJob = async (jobId: string) => {
    try {
      const { job } = await retryKnowledgeJob(jobId);
      setKnowledgeJobs((items) => items.map((item) => (item.id === job.id ? job : item)));
      setNotice(`已重新提交 ${job.filename}`);
    } catch {
      setNotice('重试失败，请稍后再试');
    }
  };

  const handleReloadKnowledge = async () => {
    if (!window.confirm('确定要重新加载知识库吗？将重新解析项目内文档。')) return;
    setLoading(true);
    setNotice('');
    try {
      const res = await reloadAIKnowledge();
      setNotice(`知识库重新加载成功：${res.totalDocuments} 条`);
      loadKnowledge();
      loadAIStats();
    } catch {
      setNotice('重新加载失败');
    } finally {
      setLoading(false);
    }
  };

  const handleTestChat = async () => {
    if (!testMessage.trim()) return;
    setTesting(true);
    try {
      const data = await testAIChat(testMessage);
      setTestResponse(JSON.stringify(data, null, 2));
    } catch (e) {
      setTestResponse(`测试失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTesting(false);
    }
  };

  const handleUpdateConfig = async () => {
    setNotice('');
    try {
      const res = await updateAIConfig(modelConfig);
      setNotice(res.message || '配置更新成功');
      loadAIStats();
    } catch {
      setNotice('配置更新失败');
    }
  };

  const handleNavClick = (path: string) => {
    setActiveNav(path.replace('/', ''));
    navigate(path);
  };

  const sidebar = (
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
  );

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#f3f4f6' }}>
      {sidebar}

      <main style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#1f2937' }}>AI 管理</h1>
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#6b7280' }}>知识库管理与模型配置</p>
          </div>
          {aiStats && (
            <Badge variant={aiStats.vectorDBStatus === 'healthy' ? 'success' : 'error'}>
              向量库 {aiStats.vectorDBStatus === 'healthy' ? '正常' : '异常'}
            </Badge>
          )}
        </div>

        {/* 统计卡片 */}
        {aiStats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px' }}>
            <Card padding="md">
              <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>知识库文档</p>
              <p style={{ margin: '8px 0 0', fontSize: '32px', fontWeight: 700, color: '#1f2937' }}>{aiStats.totalDocuments}</p>
            </Card>
            <Card padding="md">
              <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>当前模型</p>
              <p style={{ margin: '8px 0 0', fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>{aiStats.modelName || '-'}</p>
            </Card>
            <Card padding="md">
              <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>API 地址</p>
              <p style={{ margin: '8px 0 0', fontSize: '14px', fontWeight: 500, color: '#1f2937', wordBreak: 'break-all' }}>{aiStats.apiBase || '-'}</p>
            </Card>
            <Card padding="md">
              <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>最后更新</p>
              <p style={{ margin: '8px 0 0', fontSize: '14px', fontWeight: 500, color: '#1f2937' }}>{aiStats.lastUpdated || '-'}</p>
            </Card>
          </div>
        )}

        {/* 标签页 */}
        <div style={{ borderBottom: '1px solid #e5e7eb', marginBottom: '24px', display: 'flex', gap: '24px' }}>
          {(
            [
              { key: 'knowledge' as const, label: '知识库管理' },
              { key: 'config' as const, label: '模型配置' },
              { key: 'test' as const, label: '测试对话' },
            ]
          ).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: '12px 0',
                border: 'none',
                background: 'none',
                fontSize: '15px',
                fontWeight: activeTab === tab.key ? 600 : 400,
                color: activeTab === tab.key ? '#6366f1' : '#6b7280',
                borderBottom: activeTab === tab.key ? '2px solid #6366f1' : 'none',
                cursor: 'pointer',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {notice && (
          <p style={{ margin: '0 0 16px', fontSize: '13px', color: '#16a34a' }}>{notice}</p>
        )}

        {/* 知识库管理 */}
        {activeTab === 'knowledge' && (
          <div>
            <Card padding="md" style={{ marginBottom: '16px' }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>上传知识库文件</h3>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  type="file"
                  multiple
                  accept=".json,.txt,.md,.pdf,.docx"
                  onChange={(e) => setUploadFiles(Array.from(e.target.files || []))}
                  style={{ flex: 1, minWidth: '200px' }}
                />
                <Button variant="primary" onClick={handleFileUpload} disabled={uploadFiles.length === 0 || uploading} loading={uploading}>
                  {uploading ? '提交中...' : `上传${uploadFiles.length > 0 ? ` (${uploadFiles.length})` : ''}`}
                </Button>
                <Button variant="outline" onClick={handleReloadKnowledge} disabled={loading}>
                  🔄 重新加载
                </Button>
              </div>
              <p style={{ margin: '12px 0 0', fontSize: '12px', color: '#9ca3af' }}>支持格式：JSON (Q&A)、TXT、Markdown、PDF、Word</p>
            </Card>

            {knowledgeJobs.length > 0 && (
              <Card padding="md" style={{ marginBottom: '16px' }}>
                <h3 style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>导入任务</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {knowledgeJobs.slice(0, 10).map((job) => {
                    const statusLabel = {
                      pending: '等待中',
                      processing: '处理中',
                      completed: job.duplicateOf ? '已跳过重复' : '已完成',
                      failed: '失败',
                    }[job.status];
                    const badgeVariant = job.status === 'failed'
                      ? 'error'
                      : job.status === 'completed'
                        ? 'success'
                        : job.status === 'processing'
                          ? 'info'
                          : 'warning';
                    return (
                      <div key={job.id} style={{ padding: '12px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                              <span style={{ fontSize: '13px', fontWeight: 500, color: '#374151', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.filename}</span>
                              <Badge variant={badgeVariant} size="sm">{statusLabel}</Badge>
                            </div>
                            <div style={{ height: '6px', marginTop: '9px', background: '#e5e7eb', borderRadius: '999px', overflow: 'hidden' }}>
                              <div style={{ height: '100%', width: `${job.progress}%`, background: job.status === 'failed' ? '#ef4444' : '#6366f1', transition: 'width 0.2s' }} />
                            </div>
                            <p style={{ margin: '6px 0 0', fontSize: '11px', color: job.status === 'failed' ? '#dc2626' : '#6b7280' }}>
                              {job.error || `${job.progress}% · 已索引 ${job.documentsIndexed}/${job.documentsTotal} 条`}
                            </p>
                          </div>
                          {job.status === 'failed' && (
                            <Button variant="outline" size="sm" onClick={() => handleRetryJob(job.id)}>重试</Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            )}

            <Card padding="md">
              <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>知识库内容（{knowledgeItems.length} 条）</h3>
              {loading ? (
                <p style={{ textAlign: 'center', padding: '40px', color: '#9ca3af', fontSize: '13px', margin: 0 }}>加载中...</p>
              ) : knowledgeItems.length === 0 ? (
                <p style={{ textAlign: 'center', padding: '40px', color: '#9ca3af', fontSize: '13px', margin: 0 }}>
                  暂无知识库数据，请先上传文件
                </p>
              ) : (
                <div style={{ maxHeight: '480px', overflowY: 'auto' }}>
                  {knowledgeItems.map((item, index) => (
                    <div key={item.id || index} style={{ padding: '14px', borderBottom: '1px solid #f3f4f6' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <Badge variant="info" size="sm">{item.category || '未分类'}</Badge>
                        <span style={{ fontSize: '12px', color: '#9ca3af' }}>来源: {item.source}</span>
                      </div>
                      <div style={{ color: '#374151', lineHeight: 1.6, fontSize: '14px' }}>
                        {item.text.substring(0, 200)}
                        {item.text.length > 200 && '...'}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        )}

        {/* 模型配置 */}
        {activeTab === 'config' && (
          <Card padding="lg" style={{ maxWidth: '640px' }}>
            <h3 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>模型配置</h3>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>API Key</label>
              <input
                type="password"
                value={modelConfig.apiKey}
                onChange={(e) => setModelConfig({ ...modelConfig, apiKey: e.target.value })}
                placeholder="sk-..."
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '14px' }}
              />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>服务商</label>
              <select
                value={findProvider(modelConfig.apiBase)?.name || '__custom__'}
                onChange={(e) => {
                  const provider = PROVIDERS.find((p) => p.name === e.target.value);
                  if (provider) {
                    setModelConfig({
                      ...modelConfig,
                      apiBase: provider.apiBase,
                      model: provider.models[0].value,
                    });
                  }
                }}
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '14px' }}
              >
                {PROVIDERS.map((p) => (
                  <option key={p.name} value={p.name}>{p.name}</option>
                ))}
                <option value="__custom__">自定义 / 其他</option>
              </select>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>API Base URL</label>
              <input
                type="text"
                value={modelConfig.apiBase}
                onChange={(e) => setModelConfig({ ...modelConfig, apiBase: e.target.value })}
                placeholder="https://api.openai.com/v1"
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '14px' }}
              />
              <div style={{ marginTop: '6px', fontSize: '12px', color: '#9ca3af' }}>支持任意兼容 OpenAI 协议的接口，可直接输入自定义地址</div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>模型名称</label>
              <input
                type="text"
                list="model-presets"
                value={modelConfig.model}
                onChange={(e) => setModelConfig({ ...modelConfig, model: e.target.value })}
                placeholder="请输入模型名称"
                style={{ width: '100%', padding: '10px 12px', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '14px' }}
              />
              <datalist id="model-presets">
                {(findProvider(modelConfig.apiBase)?.models || PROVIDERS.flatMap((p) => p.models)).map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </datalist>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>检索 Top K: {modelConfig.topK}</label>
              <input
                type="range"
                min="1"
                max="10"
                value={modelConfig.topK}
                onChange={(e) => setModelConfig({ ...modelConfig, topK: Number(e.target.value) })}
                style={{ width: '100%' }}
              />
            </div>

            <div style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>相似度阈值: {modelConfig.similarityThreshold}</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={modelConfig.similarityThreshold}
                onChange={(e) => setModelConfig({ ...modelConfig, similarityThreshold: Number(e.target.value) })}
                style={{ width: '100%' }}
              />
            </div>

            <Button variant="primary" onClick={handleUpdateConfig}>保存配置</Button>
          </Card>
        )}

        {/* 测试对话 */}
        {activeTab === 'test' && (
          <Card padding="lg">
            <h3 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: 600, color: '#1f2937' }}>测试 AI 对话</h3>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>测试问题</label>
              <textarea
                value={testMessage}
                onChange={(e) => setTestMessage(e.target.value)}
                placeholder="输入测试问题..."
                rows={3}
                style={{ width: '100%', padding: '12px', border: '1px solid #e5e7eb', borderRadius: '8px', fontSize: '14px', resize: 'vertical' }}
              />
            </div>
            <Button
              variant="primary"
              onClick={handleTestChat}
              disabled={!testMessage.trim() || testing}
              loading={testing}
              style={{ marginBottom: '16px' }}
            >
              {testing ? '测试中...' : '开始测试'}
            </Button>

            {testResponse && (
              <div>
                <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: '#374151', marginBottom: '8px' }}>测试结果</label>
                <pre style={{ background: '#f9fafb', padding: '16px', borderRadius: '8px', overflow: 'auto', maxHeight: '400px', fontSize: '13px', lineHeight: 1.6 }}>
                  {testResponse}
                </pre>
              </div>
            )}
          </Card>
        )}
      </main>
    </div>
  );
}
