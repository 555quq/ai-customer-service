"""向量数据库封装 - Qdrant"""
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter, FilterSelector, MatchValue,
    VectorParams, PointStruct
)
from typing import List, Dict, Optional
from loguru import logger
from contextlib import contextmanager
import time
import uuid

from ..utils.metrics import qdrant_operation_duration_seconds, qdrant_operations_total


@contextmanager
def _observe_qdrant(operation: str):
    started = time.perf_counter()
    result = "error"
    try:
        yield
        result = "success"
    finally:
        qdrant_operation_duration_seconds.labels(operation=operation).observe(
            time.perf_counter() - started
        )
        qdrant_operations_total.labels(operation=operation, result=result).inc()


class VectorStore:
    """向量数据库管理（Qdrant）"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "knowledge_base",
        vector_size: int = 1536
    ):
        # 连接与集合检查由 AIEngine.initialize 统一完成，构造对象时不访问网络。
        self.host = host
        self.port = port
        self._client: Optional[QdrantClient] = None
        self.collection_name = collection_name
        self.vector_size = vector_size

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                host=self.host,
                port=self.port,
                check_compatibility=False,
            )
        return self._client

    @client.setter
    def client(self, value: QdrantClient) -> None:
        self._client = value

    def _ensure_collection(self):
        """确保集合存在"""
        try:
            with _observe_qdrant("ensure_collection"):
                collections = self.client.get_collections().collections
                exists = any(c.name == self.collection_name for c in collections)

                if not exists:
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(
                            size=self.vector_size,
                            distance=Distance.COSINE
                        )
                    )
                    logger.info(f"创建向量集合: {self.collection_name}")
        except Exception as e:
            logger.error(f"确保集合存在失败: {e}")
            raise

    async def add_documents(
        self,
        texts: List[str],
        embeddings: List[List[float]],
        metadata: List[Dict] = None
    ) -> List[str]:
        """
        批量添加文档

        Args:
            texts: 文本列表
            embeddings: 对应的向量列表
            metadata: 元数据列表

        Returns:
            文档ID列表
        """
        if len(texts) != len(embeddings):
            raise ValueError("texts和embeddings长度必须一致")

        if metadata and len(metadata) != len(texts):
            raise ValueError("metadata长度必须与texts一致")

        points = []
        ids = []

        for i, (text, embedding) in enumerate(zip(texts, embeddings)):
            doc_id = str(uuid.uuid4())
            ids.append(doc_id)

            payload = {
                "text": text,
                "metadata": metadata[i] if metadata else {}
            }

            points.append(
                PointStruct(
                    id=doc_id,
                    vector=embedding,
                    payload=payload
                )
            )

        try:
            with _observe_qdrant("upsert"):
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points
                )
            logger.info(f"成功添加 {len(points)} 个文档到向量库")
            return ids

        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            raise

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        score_threshold: float = 0.7
    ) -> List[Dict]:
        """
        向量相似度搜索

        Args:
            query_vector: 查询向量
            top_k: 返回top K个结果
            score_threshold: 相似度阈值

        Returns:
            搜索结果列表
        """
        try:
            with _observe_qdrant("search"):
                result = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    limit=top_k,
                    score_threshold=score_threshold,
                    with_payload=True,
                )
            results = result.points

            # 格式化结果
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "id": result.id,
                    "score": result.score,
                    "text": result.payload.get("text", ""),
                    "metadata": result.payload.get("metadata", {})
                })

            logger.info(f"搜索到 {len(formatted_results)} 个相关文档")
            return formatted_results

        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []

    async def scroll_documents(self, limit: int = 50, offset: int = 0) -> dict:
        """
        滚动获取文档列表（分页），用于知识库管理界面。

        Args:
            limit: 返回条数
            offset: 起始偏移

        Returns:
            {"items": [{"id","text","source","category","type"}], "total", "limit", "offset"}
        """
        try:
            # Qdrant scroll 的 offset 为游标指针，这里用「取前 offset+limit 条再切片」实现分页
            with _observe_qdrant("scroll"):
                result = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=offset + limit,
                    offset=None,
                    with_payload=True,
                    with_vectors=False,
                )
            points = result[0] or []
            info = self.get_collection_info()

            items = []
            for point in points[offset:offset + limit]:
                payload = point.payload or {}
                metadata = payload.get("metadata") or {}
                items.append({
                    "id": str(point.id),
                    "text": payload.get("text", ""),
                    "source": metadata.get("source", "unknown"),
                    "category": metadata.get("category", ""),
                    "type": metadata.get("type", ""),
                })

            return {
                "items": items,
                "total": info.get("points_count", len(points)),
                "limit": limit,
                "offset": offset,
            }
        except Exception as e:
            logger.error(f"滚动获取文档失败: {e}")
            raise

    async def delete_by_metadata(self, key: str, value: str) -> None:
        """Delete every point whose nested metadata field matches ``value``."""
        with _observe_qdrant("delete_by_metadata"):
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key=f"metadata.{key}",
                                match=MatchValue(value=value),
                            )
                        ]
                    )
                ),
                wait=True,
            )

    async def delete_collection(self):
        """删除集合"""
        try:
            with _observe_qdrant("delete_collection"):
                self.client.delete_collection(self.collection_name)
            logger.info(f"删除集合: {self.collection_name}")
        except Exception as e:
            logger.error(f"删除集合失败: {e}")

    def close(self) -> None:
        """Close the lazily-created Qdrant client, if it was used."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def get_collection_info(self) -> Dict:
        """获取集合信息"""
        try:
            with _observe_qdrant("collection_info"):
                info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.points_count,
                "points_count": info.points_count,
                "status": info.status
            }
        except Exception as e:
            logger.error(f"获取集合信息失败: {e}")
            return {}
