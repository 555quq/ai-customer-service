"""本地 Embedding 服务（fastembed ONNX，免费离线，无外部 API 依赖）"""
import asyncio
from typing import List
from loguru import logger
from fastembed import TextEmbedding


class LocalEmbedding:
    """基于 fastembed 的本地向量化服务

    首次使用会从 HuggingFace 下载模型（约 100MB），之后本地缓存。
    不依赖任何外部 API Key，完全免费。
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        cache_dir: str = "data/model_cache",
    ):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: TextEmbedding | None = None

    def _load(self) -> None:
        if self._model is None:
            logger.info(f"加载本地 embedding 模型: {self.model_name}")
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=self.cache_dir,
            )
            logger.info("本地 embedding 模型加载完成")

    def embed_sync(self, text: str) -> List[float]:
        self._load()
        vectors = list(self._model.embed([text]))
        return vectors[0].tolist()

    def embed_many_sync(self, texts: List[str]) -> List[List[float]]:
        self._load()
        return [v.tolist() for v in self._model.embed(texts)]

    async def warmup(self) -> None:
        """Load the model before the service is marked ready."""
        await asyncio.to_thread(self._load)

    async def embed(self, text: str) -> List[float]:
        """异步向量化单个文本"""
        return await asyncio.to_thread(self.embed_sync, text)

    async def embed_many(self, texts: List[str]) -> List[List[float]]:
        """异步向量化多个文本"""
        return await asyncio.to_thread(self.embed_many_sync, texts)
