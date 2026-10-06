"""Dify AI API 客户端服务"""
from dataclasses import dataclass
import httpx
from loguru import logger


@dataclass
class AIResponse:
    """AI 响应数据结构"""
    text: str
    confidence: float
    metadata: dict


class DifyService:
    """Dify AI API 异步客户端"""

    def __init__(self, api_url: str, api_key: str) -> None:
        """初始化 Dify 服务

        Args:
            api_url: Dify API 基础地址
            api_key: API 密钥
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        headers = {'Content-Type': 'application/json'}
        if api_key and api_key.isascii():
            headers['Authorization'] = f'Bearer {api_key}'
        else:
            logger.warning("Dify API Key 未配置或包含非法字符，AI 调用将返回不可用状态")
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=60.0
        )

    async def chat(
        self,
        message: str,
        user_id: str,
        conversation_id: str = ''
    ) -> AIResponse:
        """调用 Dify 对话接口

        Args:
            message: 用户消息
            user_id: 用户 ID
            conversation_id: 会话 ID（可选，用于多轮对话）

        Returns:
            AI 响应结果
        """
        url = f"{self.api_url}/chat-messages" if self.api_url.endswith('/v1') else f"{self.api_url}/v1/chat-messages"
        payload = {
            'inputs': {},
            'query': message,
            'user': user_id,
            'conversation_id': conversation_id,
            'response_mode': 'blocking'
        }

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            # 提取响应文本
            text = data.get('answer', '')

            # 提取置信度（从 metadata.confidence 获取，默认 1.0）
            metadata = data.get('metadata', {})
            confidence = metadata.get('confidence', 1.0)

            logger.info(f"Dify AI 响应成功，置信度: {confidence}")

            return AIResponse(
                text=text,
                confidence=confidence,
                metadata=metadata
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Dify API 调用失败: {e.response.status_code} - {e.response.text}")
            return AIResponse(
                text='抱歉，AI 服务暂时不可用，请稍后再试',
                confidence=0.0,
                metadata={'error': str(e)}
            )
        except Exception as e:
            logger.error(f"Dify API 调用异常: {str(e)}")
            return AIResponse(
                text='抱歉，处理您的请求时出现错误',
                confidence=0.0,
                metadata={'error': str(e)}
            )

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        await self.client.aclose()
