"""Redis 缓存和会话状态管理模块"""
import json
from typing import Any, Optional

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from loguru import logger


class ConversationState:
    """对话状态数据类"""

    def __init__(
        self,
        conversation_id: str,
        unresolved_count: int = 0,
        last_intent: str = "",
        last_confidence: float = 1.0,
        message_count: int = 0
    ):
        self.conversation_id = conversation_id
        self.unresolved_count = unresolved_count
        self.last_intent = last_intent
        self.last_confidence = last_confidence
        self.message_count = message_count

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "conversation_id": self.conversation_id,
            "unresolved_count": self.unresolved_count,
            "last_intent": self.last_intent,
            "last_confidence": self.last_confidence,
            "message_count": self.message_count
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationState":
        """从字典创建"""
        return cls(
            conversation_id=data.get("conversation_id", ""),
            unresolved_count=data.get("unresolved_count", 0),
            last_intent=data.get("last_intent", ""),
            last_confidence=data.get("last_confidence", 1.0),
            message_count=data.get("message_count", 0)
        )


class RedisCache:
    """Redis 缓存管理器"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: Optional[str] = None,
        db: int = 0
    ):
        """初始化 Redis 缓存

        Args:
            host: Redis 主机地址
            port: Redis 端口
            password: Redis 密码
            db: Redis 数据库编号
        """
        if not REDIS_AVAILABLE:
            logger.warning("redis 模块未安装，缓存功能将不可用")
            self.client = None
            return

        self.client = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db,
            decode_responses=True
        )
        logger.info(f"Redis 缓存已初始化: {host}:{port}")

    async def ping(self) -> bool:
        """测试 Redis 连接

        Returns:
            连接是否正常
        """
        if not self.client:
            return False

        try:
            await self.client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis 连接失败: {str(e)}")
            return False

    async def get(self, key: str) -> Optional[str]:
        """获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值，如果不存在返回 None
        """
        if not self.client:
            return None

        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"获取缓存失败 [{key}]: {str(e)}")
            return None

    async def set(
        self,
        key: str,
        value: str,
        expire: Optional[int] = None
    ) -> bool:
        """设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            expire: 过期时间（秒），None 表示永不过期

        Returns:
            是否设置成功
        """
        if not self.client:
            return False

        try:
            if expire:
                await self.client.setex(key, expire, value)
            else:
                await self.client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"设置缓存失败 [{key}]: {str(e)}")
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        if not self.client:
            return False

        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"删除缓存失败 [{key}]: {str(e)}")
            return False

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """递增计数器

        Args:
            key: 缓存键
            amount: 递增量

        Returns:
            递增后的值
        """
        if not self.client:
            return None

        try:
            return await self.client.incrby(key, amount)
        except Exception as e:
            logger.error(f"递增计数器失败 [{key}]: {str(e)}")
            return None

    # === 会话状态管理 ===

    def _conversation_key(self, conversation_id: str) -> str:
        """生成会话状态键

        Args:
            conversation_id: 会话 ID

        Returns:
            Redis 键
        """
        return f"conversation:{conversation_id}"

    async def get_conversation_state(
        self,
        conversation_id: str
    ) -> Optional[ConversationState]:
        """获取会话状态

        Args:
            conversation_id: 会话 ID

        Returns:
            会话状态对象，如果不存在返回 None
        """
        key = self._conversation_key(conversation_id)
        data = await self.get(key)

        if not data:
            return None

        try:
            state_dict = json.loads(data)
            return ConversationState.from_dict(state_dict)
        except Exception as e:
            logger.error(f"解析会话状态失败 [{conversation_id}]: {str(e)}")
            return None

    async def set_conversation_state(
        self,
        state: ConversationState,
        expire: int = 3600
    ) -> bool:
        """保存会话状态

        Args:
            state: 会话状态对象
            expire: 过期时间（秒），默认 1 小时

        Returns:
            是否保存成功
        """
        key = self._conversation_key(state.conversation_id)
        value = json.dumps(state.to_dict())
        return await self.set(key, value, expire)

    async def update_conversation_state(
        self,
        conversation_id: str,
        unresolved_count: Optional[int] = None,
        last_intent: Optional[str] = None,
        last_confidence: Optional[float] = None,
        increment_message: bool = False
    ) -> Optional[ConversationState]:
        """更新会话状态

        Args:
            conversation_id: 会话 ID
            unresolved_count: 未解决次数
            last_intent: 最后意图
            last_confidence: 最后置信度
            increment_message: 是否递增消息计数

        Returns:
            更新后的会话状态
        """
        # 获取现有状态或创建新状态
        state = await self.get_conversation_state(conversation_id)
        if not state:
            state = ConversationState(conversation_id=conversation_id)

        # 更新字段
        if unresolved_count is not None:
            state.unresolved_count = unresolved_count
        if last_intent is not None:
            state.last_intent = last_intent
        if last_confidence is not None:
            state.last_confidence = last_confidence
        if increment_message:
            state.message_count += 1

        # 保存状态
        success = await self.set_conversation_state(state)

        return state if success else None

    async def increment_unresolved(
        self,
        conversation_id: str
    ) -> int:
        """递增未解决次数

        Args:
            conversation_id: 会话 ID

        Returns:
            递增后的未解决次数
        """
        state = await self.get_conversation_state(conversation_id)
        if not state:
            state = ConversationState(conversation_id=conversation_id)

        state.unresolved_count += 1
        await self.set_conversation_state(state)

        return state.unresolved_count

    async def reset_unresolved(self, conversation_id: str) -> bool:
        """重置未解决次数

        Args:
            conversation_id: 会话 ID

        Returns:
            是否重置成功
        """
        state = await self.get_conversation_state(conversation_id)
        if not state:
            return True  # 不存在就认为已重置

        state.unresolved_count = 0
        return await self.set_conversation_state(state)

    async def delete_conversation_state(self, conversation_id: str) -> bool:
        """删除会话状态

        Args:
            conversation_id: 会话 ID

        Returns:
            是否删除成功
        """
        key = self._conversation_key(conversation_id)
        return await self.delete(key)

    # === 问答缓存 ===

    def _qa_cache_key(self, question: str) -> str:
        """生成问答缓存键

        Args:
            question: 问题文本

        Returns:
            Redis 键
        """
        import hashlib
        question_hash = hashlib.md5(question.encode()).hexdigest()
        return f"qa_cache:{question_hash}"

    async def get_cached_answer(self, question: str) -> Optional[str]:
        """获取缓存的答案

        Args:
            question: 问题文本

        Returns:
            缓存的答案，如果不存在返回 None
        """
        key = self._qa_cache_key(question)
        return await self.get(key)

    async def cache_answer(
        self,
        question: str,
        answer: str,
        expire: int = 1800
    ) -> bool:
        """缓存问答

        Args:
            question: 问题文本
            answer: 答案文本
            expire: 过期时间（秒），默认 30 分钟

        Returns:
            是否缓存成功
        """
        key = self._qa_cache_key(question)
        return await self.set(key, answer, expire)

    async def close(self):
        """关闭 Redis 连接"""
        if self.client:
            await self.client.close()
            logger.info("Redis 连接已关闭")
