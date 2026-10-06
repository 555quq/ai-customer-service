"""Chatwoot Webhook 数据模型

定义 Chatwoot message_created 事件的 Webhook payload 结构
使用 Pydantic v2 进行数据验证
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Sender(BaseModel):
    """消息发送者"""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(..., description="发送者 ID")
    name: str = Field(..., description="发送者姓名")


class Message(BaseModel):
    """Chatwoot 消息"""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(..., description="消息 ID")
    content: str = Field(..., description="消息内容")
    message_type: Literal["incoming", "outgoing"] = Field(..., description="消息类型")
    private: bool = Field(..., description="是否私密消息")
    sender: Optional[Sender] = Field(None, description="发送者信息")
    created_at: int | str = Field(..., description="创建时间戳")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str, info) -> str:
        """验证 incoming 消息内容非空"""
        # 获取 message_type 字段值
        data = info.data
        if data.get("message_type") == "incoming" and len(v.strip()) == 0:
            raise ValueError("incoming 消息内容不能为空")
        return v


class Conversation(BaseModel):
    """对话信息"""

    model_config = ConfigDict(extra="allow")  # 允许额外字段

    id: int = Field(..., description="对话 ID")
    status: Literal["open", "pending", "resolved"] = Field(..., description="对话状态")


class ChatwootWebhook(BaseModel):
    """Chatwoot Webhook 请求体"""

    model_config = ConfigDict(extra="ignore")

    event: str = Field(..., description="事件类型，如 message_created")
    id: int = Field(..., description="事件 ID")
    message: Optional[Message] = Field(None, description="消息信息")
    conversation: Optional[Conversation] = Field(None, description="对话信息")

    @model_validator(mode="before")
    @classmethod
    def normalize_chatwoot_311_payload(cls, value):
        """Accept Chatwoot 3.11's flat message webhook representation."""
        if not isinstance(value, dict) or value.get("message") is not None:
            return value
        if value.get("event") != "message_created":
            return value
        message_fields = {
            key: value.get(key)
            for key in (
                "id",
                "content",
                "message_type",
                "private",
                "sender",
                "created_at",
            )
        }
        if all(
            message_fields.get(key) is not None
            for key in ("id", "content", "message_type", "private", "created_at")
        ):
            normalized = dict(value)
            normalized["message"] = message_fields
            return normalized
        return value
