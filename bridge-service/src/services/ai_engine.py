"""
开源AI引擎 - 完整实现
支持OpenAI协议、本地向量库、RAG
完全替代Dify
"""
from typing import List, Dict, Optional
from dataclasses import dataclass
from loguru import logger
import asyncio
import json
import redis.asyncio as aioredis
from ..config import settings

from .llm_client import LLMClient
from .local_embedding import LocalEmbedding
from .vector_store import VectorStore
from .knowledge_loader import KnowledgeLoader
from .ai_config import AIConfig


@dataclass
class AIResponse:
    """AI回复数据类"""
    reply: str
    confidence: float
    intent: str = "general"
    sources: List[Dict] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = []


class AIEngine:
    """
    开源AI引擎

    功能:
    - 支持OpenAI协议（兼容多种大模型）
    - 本地向量数据库（Qdrant）
    - RAG（检索增强生成）
    - 多轮对话管理
    """

    def __init__(self, config: AIConfig = None):
        self.config = config or AIConfig()

        # LLM 客户端首次调用时再创建，避免仅做健康检查/单测时初始化网络栈。
        self._llm: Optional[LLMClient] = None

        # 本地 Embedding 服务（fastembed，免费离线，中文 bge-small-zh）
        self.embedding = LocalEmbedding(
            model_name=self.config.embedding_model,
            cache_dir=self.config.embedding_cache_dir,
        )

        # 向量数据库
        self.vector_store = VectorStore(
            host=self.config.qdrant_host,
            port=self.config.qdrant_port,
            collection_name=self.config.qdrant_collection,
            vector_size=self.config.embedding_dimension
        )

        # 知识库加载器
        self.knowledge_loader = KnowledgeLoader()

        # 对话历史（内存 + Redis 可选持久化，重启不丢）
        self.conversations: Dict[str, List[Dict]] = {}
        self._redis = None
        if getattr(settings, 'redis_host', None):
            try:
                self._redis = aioredis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    password=settings.redis_password,
                    db=settings.redis_db,
                    decode_responses=True,
                )
                logger.info('Redis 对话历史持久化已启用')
            except Exception as e:
                logger.warning(f'Redis 对话历史初始化失败，降级为内存: {e}')

        logger.info("AI引擎初始化完成")

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(
                api_key=self.config.openai_api_key,
                api_base=self.config.openai_api_base,
                model=self.config.openai_model,
            )
        return self._llm

    @llm.setter
    def llm(self, value: LLMClient) -> None:
        self._llm = value

    async def initialize(self):
        """初始化：加载知识库到向量数据库"""
        try:
            self.vector_store._ensure_collection()
            # 即使 Qdrant 已有索引，也在 readiness 前预热持久化模型，
            # 避免首个访客请求承担下载与加载耗时。
            await self.embedding.warmup()
            # 检查向量库是否已有数据
            info = self.vector_store.get_collection_info()
            if info.get("points_count", 0) > 0:
                logger.info(f"向量库已有 {info['points_count']} 条数据")
                return

            # 加载知识库文件
            logger.info("开始加载知识库...")
            documents = self.knowledge_loader.load_all()

            if not documents:
                logger.warning("知识库为空，创建示例文件")
                self.knowledge_loader.save_sample_json()
                documents = self.knowledge_loader.load_all()

            # 批量向量化并存储
            await self._index_documents(documents)

            logger.info("知识库加载完成")

        except Exception as e:
            # 向量库/embedding 不可用时跳过知识库索引，AI 引擎仍可回答
            logger.warning(f"知识库初始化跳过（embedding/向量库不可用）: {e}")

    async def _index_documents(self, documents: List[Dict]):
        """
        将文档向量化并存入数据库

        Args:
            documents: 文档列表 [{"text": "...", "metadata": {...}}]
        """
        texts = [doc["text"] for doc in documents]
        metadata = [doc["metadata"] for doc in documents]

        # 批量获取向量（避免超过API限制，分批处理）
        batch_size = 100
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = []

            for text in batch_texts:
                embedding = await self.embedding.embed(text)
                batch_embeddings.append(embedding)

            all_embeddings.extend(batch_embeddings)
            logger.info(f"已向量化 {len(all_embeddings)}/{len(texts)} 个文档")

        # 存入向量库
        await self.vector_store.add_documents(
            texts=texts,
            embeddings=all_embeddings,
            metadata=metadata
        )

    async def chat(
        self,
        message: str,
        conversation_id: str,
        user_id: str = None
    ) -> AIResponse:
        """
        处理用户消息

        Args:
            message: 用户消息
            conversation_id: 会话ID
            user_id: 用户ID

        Returns:
            AI回复
        """
        try:
            # 1. 意图识别（简单关键词匹配）
            intent = self._analyze_intent(message)

            # 2. 向量检索相关知识（embedding/检索不可用时跳过 RAG，直接回答）
            search_results = []
            try:
                query_embedding = await self.embedding.embed(message)

                search_results = await self.vector_store.search(
                    query_vector=query_embedding,
                    top_k=self.config.top_k_results,
                    score_threshold=self.config.similarity_threshold
                )
            except Exception as e:
                logger.warning(f"知识库检索不可用，跳过 RAG: {e}")

            # 2.5 加载对话历史（Redis 持久化）
            await self._load_conversation(conversation_id)

            # 3. 构建对话上下文
            messages = self._build_messages(
                user_message=message,
                search_results=search_results,
                conversation_id=conversation_id
            )

            # 4. 调用LLM生成回复
            response = await self.llm.chat_completion(
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )

            # 5. 提取回复内容
            reply = response["choices"][0]["message"]["content"]

            # 6. 计算置信度
            confidence = self._calculate_confidence(search_results, reply)

            # 7. 保存对话历史
            self._save_conversation(conversation_id, message, reply)

            # 8. 返回结果
            return AIResponse(
                reply=reply,
                confidence=confidence,
                intent=intent,
                sources=[{
                    "text": r["text"][:200],
                    "score": r["score"],
                    "source": r["metadata"].get("source", "unknown"),
                    "source_id": r["metadata"].get("source_id"),
                    "chunk_id": r["metadata"].get("chunk_id"),
                } for r in search_results[:2]]
            )

        except Exception as e:
            logger.error(f"对话处理失败: {e}")
            return AIResponse(
                reply="抱歉，我遇到了一些问题。请稍后再试或联系人工客服。",
                confidence=0.0,
                intent="error"
            )

    def _analyze_intent(self, message: str) -> str:
        """
        简单的意图识别

        Args:
            message: 用户消息

        Returns:
            意图类型
        """
        # 转人工关键词
        handoff_keywords = ["人工", "转人工", "客服", "投诉", "退款"]
        if any(kw in message for kw in handoff_keywords):
            return "handoff"

        # 问候
        if any(kw in message for kw in ["你好", "您好", "hi", "hello"]):
            return "greeting"

        # 咨询
        if any(kw in message for kw in ["怎么", "如何", "什么", "哪里", "?"]):
            return "inquiry"

        return "general"

    def _build_messages(
        self,
        user_message: str,
        search_results: List[Dict],
        conversation_id: str
    ) -> List[Dict]:
        """
        构建发送给LLM的消息列表

        Args:
            user_message: 用户消息
            search_results: 检索结果
            conversation_id: 会话ID

        Returns:
            消息列表
        """
        messages = []

        # 1. 系统Prompt
        system_prompt = self.config.system_prompt

        # 2. 添加知识库上下文
        if search_results:
            context = "\n\n".join([
                f"[参考{i+1}] {r['text']}"
                for i, r in enumerate(search_results)
            ])
            system_prompt += f"\n\n知识库参考内容：\n{context}"

        messages.append({
            "role": "system",
            "content": system_prompt
        })

        # 3. 添加历史对话（最近3轮）
        history = self.conversations.get(conversation_id, [])[-6:]
        messages.extend(history)

        # 4. 添加当前用户消息
        messages.append({
            "role": "user",
            "content": user_message
        })

        return messages

    def _calculate_confidence(
        self,
        search_results: List[Dict],
        reply: str
    ) -> float:
        """
        计算回复置信度

        Args:
            search_results: 检索结果
            reply: AI回复

        Returns:
            置信度 (0-1)
        """
        if not search_results:
            return 0.3

        # 基于最高相似度分数
        max_score = max([r["score"] for r in search_results])

        # 基于检索结果数量
        count_factor = min(len(search_results) / 3, 1.0)

        # 综合计算
        confidence = max_score * 0.7 + count_factor * 0.3

        # 如果回复包含"不知道"、"不确定"等，降低置信度
        uncertain_words = ["不知道", "不确定", "不清楚", "建议", "转人工"]
        if any(word in reply for word in uncertain_words):
            confidence *= 0.7

        return round(confidence, 2)

    async def _load_conversation(self, conversation_id: str) -> None:
        """从 Redis 加载对话历史（若已持久化）"""
        if not self._redis:
            return
        try:
            data = await self._redis.get(f"conversation:{conversation_id}")
            if data:
                history = json.loads(data)
                if isinstance(history, list) and history:
                    self.conversations[conversation_id] = history
                    logger.debug(f"从 Redis 加载对话历史: {len(history)} 条")
        except Exception as e:
            logger.warning(f"Redis 对话加载失败: {e}")

    async def _redis_set_conversation(self, conversation_id: str, history: list) -> None:
        """后台将对话历史写入 Redis"""
        if not self._redis:
            return
        try:
            await self._redis.set(
                f"conversation:{conversation_id}",
                json.dumps(history, ensure_ascii=False),
                ex=86400 * 7,
            )
        except Exception as e:
            logger.warning(f"Redis 对话保存失败: {e}")

    def _save_conversation(
        self,
        conversation_id: str,
        user_message: str,
        ai_reply: str
    ):
        """保存对话历史"""
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []

        self.conversations[conversation_id].extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": ai_reply}
        ])

        # 只保留最近10轮对话
        if len(self.conversations[conversation_id]) > 20:
            self.conversations[conversation_id] = \
                self.conversations[conversation_id][-20:]

        # 后台持久化到 Redis
        if self._redis:
            history = list(self.conversations[conversation_id])
            asyncio.create_task(self._redis_set_conversation(conversation_id, history))

    async def reload_knowledge(self):
        """重新加载知识库"""
        logger.info("开始重新加载知识库...")

        # 清空现有数据
        await self.vector_store.delete_collection()
        self.vector_store._ensure_collection()

        # 重新加载
        await self.initialize()

    async def add_knowledge(
        self,
        text: str,
        metadata: Dict = None
    ):
        """
        动态添加单条知识

        Args:
            text: 文本内容
            metadata: 元数据
        """
        embedding = await self.embedding.embed(text)

        await self.vector_store.add_documents(
            texts=[text],
            embeddings=[embedding],
            metadata=[metadata or {}]
        )

        logger.info(f"添加知识: {text[:50]}...")

    async def close(self):
        """关闭连接"""
        if self._llm is not None:
            await self._llm.close()
        self.vector_store.close()
        if self._redis is not None:
            await self._redis.aclose()
        logger.info("AI引擎已关闭")


# 使用示例
if __name__ == "__main__":
    async def test():
        # 初始化AI引擎
        engine = AIEngine()
        await engine.initialize()

        # 测试对话
        response = await engine.chat(
            message="你们的营业时间是什么？",
            conversation_id="test-123"
        )

        print(f"回复: {response.reply}")
        print(f"置信度: {response.confidence}")
        print(f"意图: {response.intent}")
        print(f"来源: {response.sources}")

        await engine.close()

    asyncio.run(test())
