"""LLM客户端 - 支持OpenAI协议"""
import asyncio
import httpx
from typing import List, Dict
from loguru import logger


class LLMClient:
    """
    OpenAI API兼容的LLM客户端

    支持:
    - OpenAI (GPT-4, GPT-3.5)
    - DeepSeek
    - 通义千问
    - Moonshot
    - 任何OpenAI兼容接口
    """

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://api.openai.com/v1",
        model: str = "gpt-3.5-turbo",
        timeout: int = 90,
        max_retries: int = 2
    ):
        self.api_key = api_key
        self.api_base = api_base.rstrip('/')
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(timeout=timeout)

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        stream: bool = False
    ) -> Dict:
        """
        调用Chat Completion API

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数（0-2），越高越随机
            max_tokens: 最大生成token数
            stream: 是否流式输出

        Returns:
            API响应
        """
        last_error: Exception = None
        for attempt in range(1 + self.max_retries):
            try:
                response = await self.client.post(
                    f"{self.api_base}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": stream
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                # 429/5xx 可重试
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        wait = 2 ** attempt
                        logger.warning(
                            f"LLM API 返回 {response.status_code}，"
                            f"{wait}s 后重试（{attempt + 1}/{self.max_retries}）"
                        )
                        await asyncio.sleep(wait)
                        continue
                response.raise_for_status()
                return response.json()

            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        f"LLM API 请求异常（{type(e).__name__}: {e}），"
                        f"{wait}s 后重试（{attempt + 1}/{self.max_retries}）"
                    )
                    await asyncio.sleep(wait)
                    continue
            except httpx.HTTPError:
                raise

        # 重试耗尽，抛出原始异常（ai_engine 会捕获并返回兜底回复）
        if isinstance(last_error, httpx.TimeoutException):
            logger.error(
                f"LLM API 调用超时（{self.timeout}s），重试 {self.max_retries} 次后仍失败"
            )
        elif last_error is not None:
            logger.error(
                f"LLM API 调用失败: {type(last_error).__name__}: {last_error}"
            )
        if last_error is not None:
            raise last_error
        raise httpx.HTTPError("LLM API 请求失败（无重试尝试）")

    async def get_embedding(
        self,
        text: str,
        model: str = None
    ) -> List[float]:
        """
        获取文本嵌入向量

        Args:
            text: 输入文本
            model: 嵌入模型名称

        Returns:
            向量列表
        """
        embedding_model = model or "text-embedding-3-small"

        try:
            response = await self.client.post(
                f"{self.api_base}/embeddings",
                json={
                    "model": embedding_model,
                    "input": text
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]

        except httpx.HTTPError as e:
            logger.error(f"Embedding API调用失败: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"响应内容: {e.response.text}")
            raise

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
