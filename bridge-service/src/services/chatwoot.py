"""Chatwoot API 客户端服务"""
from typing import Optional
import httpx
from loguru import logger
import time

from ..utils.metrics import chatwoot_api_time, chatwoot_requests_total


def _extract_error(e: httpx.HTTPStatusError) -> str:
    """提取 Chatwoot API 错误信息（截断避免刷屏）。"""
    try:
        text = e.response.text
        return text[:300]
    except Exception:
        return str(e)


class ChatwootService:
    """Chatwoot API 异步客户端"""

    def __init__(self, base_url: str, api_token: str, account_id: str) -> None:
        """初始化 Chatwoot 服务

        Args:
            base_url: Chatwoot API 基础地址
            api_token: API 访问令牌
            account_id: 账户 ID
        """
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.account_id = account_id
        self.client = httpx.AsyncClient(
            headers={'api_access_token': api_token},
            timeout=30.0
        )

    async def _observe(
        self,
        operation: str,
        request,
        accepted_statuses: set[int] | None = None,
    ) -> httpx.Response:
        """Await one Chatwoot call and record a bounded operation label."""
        started = time.perf_counter()
        result = "error"
        try:
            response = await request
            if response.status_code not in (accepted_statuses or set()):
                response.raise_for_status()
            result = "success"
            return response
        finally:
            chatwoot_api_time.labels(operation=operation).observe(time.perf_counter() - started)
            chatwoot_requests_total.labels(operation=operation, result=result).inc()

    async def send_message(
        self,
        conversation_id: str,
        content: str,
        message_type: str = 'outgoing',
        private: bool = False
    ) -> dict:
        """发送消息到会话

        Args:
            conversation_id: 会话 ID
            content: 消息内容
            message_type: 消息类型（outgoing/incoming）
            private: 是否为私有消息（内部备注）

        Returns:
            API 响应数据

        Raises:
            httpx.HTTPStatusError: HTTP 请求失败
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"
        payload = {
            'content': content,
            'message_type': message_type,
            'private': private
        }

        try:
            response = await self._observe("send_message", self.client.post(url, json=payload))
            logger.info(f"消息已发送到会话 {conversation_id}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"发送消息失败: {e.response.status_code} - {e.response.text}")
            raise

    async def create_contact(self, name: str, inbox_id: int, source_id: str = '') -> dict:
        """在 API 渠道中创建访客联系人（转人工使用）。

        Args:
            name: 访客名称
            inbox_id: 渠道 inbox ID
            source_id: 外部标识（API 渠道推荐，用于识别同一访客）

        Returns:
            Chatwoot 联系人数据
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/contacts"
        payload: dict = {
            'inbox_id': inbox_id,
            'name': name,
        }
        if source_id:
            payload['source_id'] = source_id

        try:
            response = await self._observe("create_contact", self.client.post(url, json=payload))
            logger.info(f"已创建联系人: {name} (source_id={source_id})")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"创建联系人失败: {e.response.status_code} - {_extract_error(e)}")
            raise

    async def create_conversation(
        self,
        inbox_id: int,
        contact_id: int,
    ) -> dict:
        """通过 API 渠道创建会话（不附带消息，访客消息随后单独发送以保证归属正确）。

        Args:
            inbox_id: 渠道 inbox ID
            contact_id: 联系人 ID

        Returns:
            Chatwoot 会话数据
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations"
        payload = {
            'inbox_id': inbox_id,
            'contact_id': contact_id,
        }

        try:
            response = await self._observe("create_conversation", self.client.post(url, json=payload))
            logger.info(f"已创建转人工会话 inbox={inbox_id} contact={contact_id}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"创建会话失败: {e.response.status_code} - {_extract_error(e)}")
            raise

    async def create_label(self, label: str) -> dict:
        """确保标签存在（不存在则创建）。"""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/labels"
        payload = {'title': label}

        try:
            response = await self._observe(
                "create_label",
                self.client.post(url, json=payload),
                accepted_statuses={422},
            )
            if response.status_code == 422:
                logger.debug(f"标签已存在: {label}")
                return {}
            logger.info(f"已创建标签: {label}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"创建标签失败: {e.response.status_code} - {_extract_error(e)}")
            return {}

    async def list_conversations(self, status: str = 'open', page: int = 1, per_page: int = 30) -> dict:
        """获取会话列表。

        Args:
            status: 会话状态（open/pending/resolved/all 等）
            page: 页码（从 1 开始）
            per_page: 每页数量

        Returns:
            Chatwoot 会话列表响应（含 data.payload 与 data.meta 分页信息）
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations"
        params = {'status': status, 'page': page, 'per_page': per_page}

        try:
            response = await self._observe("list_conversations", self.client.get(url, params=params))
            logger.debug(f"已获取会话列表: {status} page={page}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"获取会话列表失败: {e.response.status_code} - {e.response.text}")
            raise

    async def list_all_conversations(self, status: str = 'all') -> list[dict]:
        """迭代 Chatwoot 分页获取全部会话（用于统计/聚合）。

        Args:
            status: 会话状态过滤

        Returns:
            全部会话 payload 列表（已拍平）
        """
        all_items: list[dict] = []
        page = 1
        while True:
            data = await self.list_conversations(status=status, page=page, per_page=100)
            payload = data.get("data", {}).get("payload", [])
            meta = data.get("data", {}).get("meta", {})
            all_items.extend(payload)
            if not payload:
                break
            next_page = meta.get("next_page")
            if next_page is not None and str(next_page) != str(page):
                page = int(next_page)
            elif meta.get("total_pages") and page < int(meta["total_pages"]):
                page += 1
            else:
                break
            if page > 200:  # 安全上限，防止无限循环
                logger.warning("获取全部会话达到分页上限 200，提前结束")
                break
        return all_items

    async def add_label(self, conversation_id: str, label: str) -> dict:
        """为会话添加标签

        Args:
            conversation_id: 会话 ID
            label: 标签名称

        Returns:
            API 响应数据

        Raises:
            httpx.HTTPStatusError: HTTP 请求失败
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/labels"
        payload = {'labels': [label]}

        try:
            response = await self._observe("add_label", self.client.post(url, json=payload))
            logger.info(f"标签 '{label}' 已添加到会话 {conversation_id}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"添加标签失败: {e.response.status_code} - {e.response.text}")
            raise

    async def set_labels(self, conversation_id: str, labels: list[str]) -> dict:
        """设置会话标签。"""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/labels"
        payload = {'labels': labels}

        try:
            response = await self._observe("set_labels", self.client.post(url, json=payload))
            logger.info(f"会话 {conversation_id} 标签已更新")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"更新标签失败: {e.response.status_code} - {e.response.text}")
            raise

    async def assign_conversation(
        self,
        conversation_id: str,
        assignee_id: Optional[int] = None
    ) -> dict:
        """分配会话给客服人员

        Args:
            conversation_id: 会话 ID
            assignee_id: 客服人员 ID，None 表示自动分配

        Returns:
            API 响应数据

        Raises:
            httpx.HTTPStatusError: HTTP 请求失败
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/assignments"
        payload = {}
        if assignee_id is not None:
            payload['assignee_id'] = assignee_id

        try:
            response = await self._observe("assign_conversation", self.client.post(url, json=payload))
            logger.info(f"会话 {conversation_id} 已分配给客服 {assignee_id or '自动分配'}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"分配会话失败: {e.response.status_code} - {_extract_error(e)}")
            raise

    async def update_status(self, conversation_id: str, status: str) -> dict:
        """更新会话状态。"""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/toggle_status"
        payload = {'status': status}

        try:
            response = await self._observe("update_status", self.client.post(url, json=payload))
            logger.info(f"会话 {conversation_id} 状态已更新为 {status}")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"更新会话状态失败: {e.response.status_code} - {e.response.text}")
            raise

    async def get_conversation(self, conversation_id: str) -> dict:
        """获取会话详情

        Args:
            conversation_id: 会话 ID

        Returns:
            会话数据

        Raises:
            httpx.HTTPStatusError: HTTP 请求失败
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}"

        try:
            response = await self._observe("get_conversation", self.client.get(url))
            logger.debug(f"已获取会话 {conversation_id} 详情")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"获取会话失败: {e.response.status_code} - {e.response.text}")
            raise

    async def get_messages(self, conversation_id: str) -> dict:
        """获取会话消息。"""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"

        try:
            response = await self._observe("get_messages", self.client.get(url))
            logger.debug(f"已获取会话 {conversation_id} 消息")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"获取会话消息失败: {e.response.status_code} - {e.response.text}")
            raise

    async def list_agents(self) -> list[dict]:
        """获取坐席列表。"""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/agents"

        try:
            response = await self._observe("list_agents", self.client.get(url))
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"获取坐席列表失败: {e.response.status_code} - {e.response.text}")
            raise

    async def list_labels(self) -> dict:
        """获取标签列表。"""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/labels"

        try:
            response = await self._observe("list_labels", self.client.get(url))
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"获取标签列表失败: {e.response.status_code} - {e.response.text}")
            raise

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        await self.client.aclose()
