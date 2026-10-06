"""First-run deployment setup endpoints."""

from typing import Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field, HttpUrl, SecretStr

from ..services.setup_service import setup_service


router = APIRouter(prefix="/api/setup", tags=["Setup"])


class SiteSetup(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    brand_color: str = Field("#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")
    locale: Literal["zh-CN", "en-US"] = "zh-CN"


class ModelSetup(BaseModel):
    provider: str = Field(..., min_length=1, max_length=50)
    api_base: HttpUrl
    api_key: SecretStr
    model: str = Field(..., min_length=1, max_length=100)


class ChatwootSetup(BaseModel):
    base_url: HttpUrl
    api_token: SecretStr
    account_id: str = Field(..., min_length=1, max_length=30)
    inbox_id: int = Field(..., gt=0)


class AdminSetup(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: SecretStr = Field(..., min_length=12, max_length=256)


class AgentSetup(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: SecretStr = Field(..., min_length=12, max_length=256)


class AIRulesSetup(BaseModel):
    welcome_message: str = Field("你好！有什么可以帮到您？", max_length=500)
    system_prompt: str = Field(..., min_length=10, max_length=8000)
    confidence_threshold: float = Field(0.7, ge=0, le=1)
    handoff_keywords: list[str] = Field(default_factory=lambda: ["人工", "投诉", "退款"])


class InitializeRequest(BaseModel):
    site: SiteSetup
    model: ModelSetup
    chatwoot: ChatwootSetup
    admin: AdminSetup
    agent: AgentSetup
    ai_rules: AIRulesSetup
    allowed_origins: list[HttpUrl] = Field(default_factory=list, max_length=20)
    verify_connections: bool = True

    def to_runtime(self) -> dict:
        data = self.model_dump(mode="json")
        data["model"]["api_key"] = self.model.api_key.get_secret_value()
        data["chatwoot"]["api_token"] = self.chatwoot.api_token.get_secret_value()
        data["admin"]["password"] = self.admin.password.get_secret_value()
        data["agent"]["password"] = self.agent.password.get_secret_value()
        return data


@router.get("/status")
async def setup_status() -> dict:
    return setup_service.status()


@router.post("/initialize", status_code=201)
async def initialize(
    payload: InitializeRequest,
    x_setup_token: str | None = Header(None, alias="X-Setup-Token"),
) -> dict:
    return await setup_service.initialize(payload.to_runtime(), x_setup_token)
