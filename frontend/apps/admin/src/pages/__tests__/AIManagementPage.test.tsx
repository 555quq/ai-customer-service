import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AIManagementPage } from '../AIManagementPage';

// 桩掉共享 API 与认证，聚焦页面交互
vi.mock('@ai-cs/shared/api', () => ({
  fetchAIStats: vi.fn(),
  fetchAIKnowledge: vi.fn(),
  fetchKnowledgeJobs: vi.fn(),
  retryKnowledgeJob: vi.fn(),
  uploadKnowledgeJob: vi.fn(),
  reloadAIKnowledge: vi.fn(),
  testAIChat: vi.fn(),
  updateAIConfig: vi.fn(),
}));
vi.mock('../../shared/AuthProvider', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    role: 'admin',
    user: { username: 'admin' },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

import {
  fetchAIStats,
  fetchAIKnowledge,
  fetchKnowledgeJobs,
  reloadAIKnowledge,
  retryKnowledgeJob,
  testAIChat,
  uploadKnowledgeJob,
} from '@ai-cs/shared/api';

const aiStats = {
  totalDocuments: 16,
  modelName: 'deepseek-v4-flash',
  apiBase: 'https://api.deepseek.com/v1',
  vectorDBStatus: 'healthy' as const,
  lastUpdated: '最近更新',
  topK: 3,
  similarityThreshold: 0.5,
};

const knowledgeResp = {
  items: [
    { id: '1', category: '常见问题', source: 'faq.json', text: '我们的营业时间是周一至周五 9:00-18:00。' },
  ],
  total: 1,
};

describe('AIManagementPage AI 管理', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchAIStats as ReturnType<typeof vi.fn>).mockResolvedValue(aiStats);
    (fetchAIKnowledge as ReturnType<typeof vi.fn>).mockResolvedValue(knowledgeResp);
    (fetchKnowledgeJobs as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], total: 0 });
  });

  it('渲染统计卡片与向量库状态', async () => {
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('AI 管理')).toBeInTheDocument();
    // 统计卡片: 文档数 16 / 当前模型
    expect(screen.getByText('16')).toBeInTheDocument();
    expect(screen.getByText('deepseek-v4-flash')).toBeInTheDocument();
    // 向量库状态徽章
    expect(screen.getByText('向量库 正常')).toBeInTheDocument();
  });

  it('知识库列表渲染条目与分类', async () => {
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );

    expect(await screen.findByText(/我们的营业时间是周一至周五/)).toBeInTheDocument();
    expect(screen.getByText('常见问题')).toBeInTheDocument();
    expect(screen.getByText('来源: faq.json')).toBeInTheDocument();
  });

  it('知识库为空时显示空态', async () => {
    (fetchAIKnowledge as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], total: 0 });
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('暂无知识库数据，请先上传文件')).toBeInTheDocument();
  });

  it('切换标签页到模型配置', async () => {
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );
    await screen.findByText('AI 管理');

    fireEvent.click(screen.getByText('模型配置'));
    expect(screen.getByText('保存配置')).toBeInTheDocument();
    // API Key 输入框由统计预填 apiBase 对应的输入
    expect(screen.getByPlaceholderText('sk-...')).toBeInTheDocument();
  });

  it('测试对话调用 API 并展示结果', async () => {
    (testAIChat as ReturnType<typeof vi.fn>).mockResolvedValue({
      reply: '测试回复内容',
      confidence: 0.9,
      intent: 'question',
      sources: [],
      message: 'ok',
    });
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );
    await screen.findByText('AI 管理');

    fireEvent.click(screen.getByText('测试对话'));
    fireEvent.change(screen.getByPlaceholderText('输入测试问题...'), {
      target: { value: '你好吗' },
    });
    fireEvent.click(screen.getByText('开始测试'));

    await waitFor(() => expect(testAIChat).toHaveBeenCalledWith('你好吗'));
    expect(await screen.findByText(/测试回复内容/)).toBeInTheDocument();
  });

  it('点击重新加载调用 reload 接口', async () => {
    (reloadAIKnowledge as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true, totalDocuments: 16, message: 'ok' });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );
    await screen.findByText('AI 管理');

    fireEvent.click(screen.getByText('🔄 重新加载'));

    await waitFor(() => expect(reloadAIKnowledge).toHaveBeenCalled());
    expect(await screen.findByText(/知识库重新加载成功：16 条/)).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it('提交知识文件后显示异步导入任务', async () => {
    const job = {
      id: 'job-1', filename: 'faq.txt', fileHash: 'hash', sourceId: 'source', ingestionId: 'ingestion',
      status: 'pending' as const, progress: 0, documentsTotal: 0, documentsIndexed: 0,
      attempts: 0, createdAt: 'now', updatedAt: 'now', error: null, duplicateOf: null,
    };
    (uploadKnowledgeJob as ReturnType<typeof vi.fn>).mockResolvedValue({ job });
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );
    await screen.findByText('AI 管理');

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['knowledge body'], 'faq.txt', { type: 'text/plain' })] } });
    fireEvent.click(screen.getByText('上传 (1)'));

    await waitFor(() => expect(uploadKnowledgeJob).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('等待中')).toBeInTheDocument();
    expect(screen.getByText(/已提交 1 个导入任务/)).toBeInTheDocument();
  });

  it('失败任务展示原因并可重试', async () => {
    const failedJob = {
      id: 'job-failed', filename: 'broken.pdf', fileHash: 'hash', sourceId: 'source', ingestionId: 'ingestion',
      status: 'failed' as const, progress: 0, documentsTotal: 0, documentsIndexed: 0,
      attempts: 1, createdAt: 'now', updatedAt: 'now', error: 'PDF 内容为空', duplicateOf: null,
    };
    (fetchKnowledgeJobs as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [failedJob], total: 1 });
    (retryKnowledgeJob as ReturnType<typeof vi.fn>).mockResolvedValue({
      job: { ...failedJob, status: 'pending', error: null },
    });
    render(
      <MemoryRouter>
        <AIManagementPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('PDF 内容为空')).toBeInTheDocument();
    fireEvent.click(screen.getByText('重试'));
    await waitFor(() => expect(retryKnowledgeJob).toHaveBeenCalledWith('job-failed'));
  });
});
