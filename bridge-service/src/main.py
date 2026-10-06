"""Bridge Service 主应用入口"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import time
from typing import Any, Optional

import httpx
from fastapi import Body, Depends, FastAPI, Request, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from loguru import logger
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field, ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import settings
from .models.webhook import ChatwootWebhook
from .services.chatwoot import ChatwootService
from .services.dify import DifyService, AIResponse
from .services.intent import IntentAnalyzer, IntentResult
from .services.handoff_store import HandoffStore, HandoffStoreUnavailable
from .services.webhook_idempotency import (
    WebhookIdempotency,
    WebhookIdempotencyUnavailable,
)
from .utils.cache import RedisCache
from .services.ai_engine import AIEngine
from .services.ai_config import AIConfig
from .routes.ai_management import router as ai_management_router, set_ai_engine
from .routes import config as config_routes
from .routes.config import router as config_router
from .routes.conversations import router as conversations_router
from .routes.knowledge import router as knowledge_router
from .routes.admin import router as admin_router
from .routes.setup import router as setup_router
from .routes.widget import (
    router as widget_router,
    set_handoff_resolver,
    widget_site_id,
)
from .services.setup_service import setup_service
from .utils.metrics import (
    ai_requests_total,
    message_counter,
    handoff_counter,
    ai_response_time,
    low_confidence_total,
    metrics_middleware,
    normalize_handoff_reason,
    normalize_webhook_event,
    webhook_counter,
    webhook_idempotency_total,
)
from .auth.dependencies import require_agent
from .auth.routes import configure_session_store, router as auth_router
from .auth.tokens import (
    AuthConfigurationError,
    TokenValidationError,
    WidgetScopeError,
    create_widget_token,
    decode_token,
    jwt_secret,
    validate_widget_token,
    validate_widget_session_token,
)
from .utils.auth import is_production, verify_webhook_signature
from .utils.config_manager import config_manager


# 全局服务实例
chatwoot: ChatwootService
dify: DifyService
intent_analyzer: IntentAnalyzer
cache: RedisCache
handoff_store: HandoffStore | None = None
webhook_idempotency: WebhookIdempotency | None = None
ai_engine: Optional[AIEngine] = None


async def request_ai_response(message: str, user_id: str, conversation_id: str) -> AIResponse:
    """Call the explicitly selected provider and expose one consistent response type."""
    provider = settings.ai_provider
    started = time.perf_counter()
    result = "error"
    try:
        if provider == "local":
            if ai_engine is None:
                raise RuntimeError("Local AI provider is not initialized")
            local_response = await ai_engine.chat(
                message=message,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            response = AIResponse(
                text=local_response.reply,
                confidence=local_response.confidence,
                metadata={
                    "intent": getattr(local_response, "intent", "general"),
                    "sources": getattr(local_response, "sources", []),
                },
            )
            result = "error" if getattr(local_response, "intent", "general") == "error" else "success"
        else:
            response = await dify.chat(
                message=message,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            result = "error" if response.metadata.get("error") else "success"
        if response.confidence < settings.confidence_threshold:
            low_confidence_total.labels(provider=provider).inc()
        return response
    except Exception:
        result = "error"
        raise
    finally:
        ai_response_time.labels(provider=provider).observe(time.perf_counter() - started)
        ai_requests_total.labels(provider=provider, result=result).inc()

# Settings already loads both project .env files explicitly as UTF-8.  Passing a
# non-existent config file keeps SlowAPI from opening the current-directory .env
# with Starlette's platform-default encoding (GBK on Chinese Windows).
limiter = Limiter(key_func=get_remote_address, config_filename=".slowapi.env")

# WebSocket 连接管理（频道式，支持客服工作台 + 访客 widget 实时推送）
class ConnectionManager:
    """管理 WebSocket 连接并广播消息。每个连接挂在一个频道下。"""
    def __init__(self):
        self.active_connections: dict[str, set[WebSocket]] = {}

    def register(self, websocket: WebSocket, channel: str = "agent") -> None:
        self.active_connections.setdefault(channel, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str = "agent") -> None:
        conns = self.active_connections.get(channel)
        if conns and websocket in conns:
            conns.discard(websocket)
            if not conns:
                self.active_connections.pop(channel, None)

    async def broadcast(self, message: dict, channel: str = "agent") -> None:
        conns = self.active_connections.get(channel)
        if not conns:
            return
        dead = []
        for connection in list(conns):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            conns.discard(connection)


manager = ConnectionManager()


def _runtime_chatwoot_config(runtime: dict[str, Any] | None) -> dict[str, Any]:
    configured = (runtime or {}).get("chatwoot")
    if configured:
        return {
            "base_url": configured["base_url"],
            "api_token": configured["api_token"],
            "account_id": configured["account_id"],
            "inbox_id": int(configured["inbox_id"]),
        }
    return {
        "base_url": settings.chatwoot_base_url,
        "api_token": settings.chatwoot_api_token,
        "account_id": settings.chatwoot_account_id,
        "inbox_id": settings.chatwoot_inbox_id,
    }


def _runtime_ai_rules(runtime: dict[str, Any] | None) -> dict[str, Any]:
    runtime = runtime or {}
    rules = runtime.get("ai_rules", {})
    legacy_ai = runtime.get("ai", {})
    legacy_handoff = runtime.get("handoff", {})
    defaults = AIConfig()
    return {
        "confidence_threshold": rules.get(
            "confidence_threshold", legacy_ai.get("confidence_threshold", settings.confidence_threshold)
        ),
        "handoff_keywords": rules.get(
            "handoff_keywords", legacy_handoff.get("keywords", settings.handoff_keywords)
        ),
        "system_prompt": rules.get("system_prompt", defaults.system_prompt),
    }


def _runtime_ai_config(runtime: dict[str, Any] | None) -> AIConfig:
    ai_config = AIConfig()
    model = (runtime or {}).get("model")
    if model:
        ai_config.openai_api_base = str(model["api_base"]).rstrip("/")
        ai_config.openai_api_key = model["api_key"]
        ai_config.openai_model = model["model"]
    ai_config.system_prompt = _runtime_ai_rules(runtime)["system_prompt"]
    return ai_config


async def _create_ai_engine(runtime: dict[str, Any] | None) -> Optional[AIEngine]:
    if settings.ai_provider != "local":
        return None
    replacement = AIEngine(config=_runtime_ai_config(runtime))
    await replacement.initialize()
    return replacement


def _apply_effective_runtime_settings(
    chatwoot_config: dict[str, Any],
    rules: dict[str, Any],
) -> None:
    settings.chatwoot_base_url = chatwoot_config["base_url"]
    settings.chatwoot_api_token = chatwoot_config["api_token"]
    settings.chatwoot_account_id = chatwoot_config["account_id"]
    settings.chatwoot_inbox_id = chatwoot_config["inbox_id"]
    settings.confidence_threshold = rules["confidence_threshold"]
    settings.handoff_keywords = rules["handoff_keywords"]


async def reload_runtime_services(runtime: dict[str, Any]) -> None:
    """Atomically replace runtime clients after all replacements are constructed."""
    global chatwoot, ai_engine
    chatwoot_config = _runtime_chatwoot_config(runtime)
    rules = _runtime_ai_rules(runtime)
    rules["confidence_threshold"] = float(rules["confidence_threshold"])
    rules["handoff_keywords"] = list(rules["handoff_keywords"])
    replacement_chatwoot = ChatwootService(
        base_url=chatwoot_config["base_url"],
        api_token=chatwoot_config["api_token"],
        account_id=chatwoot_config["account_id"],
    )
    replacement_ai: Optional[AIEngine] = None
    try:
        replacement_ai = await _create_ai_engine(runtime)
    except Exception:
        await replacement_chatwoot.close()
        if replacement_ai:
            await replacement_ai.close()
        raise

    old_chatwoot = globals().get("chatwoot")
    old_ai = ai_engine
    _apply_effective_runtime_settings(chatwoot_config, rules)
    chatwoot = replacement_chatwoot
    ai_engine = replacement_ai
    set_ai_engine(ai_engine)

    if old_chatwoot and old_chatwoot is not replacement_chatwoot:
        try:
            await old_chatwoot.close()
        except Exception as exc:
            logger.warning(f"旧 Chatwoot 客户端关闭失败: {exc}")
    if old_ai and old_ai is not replacement_ai:
        try:
            await old_ai.close()
        except Exception as exc:
            logger.warning(f"旧 AI 引擎关闭失败: {exc}")


setup_service.set_reload_callback(reload_runtime_services)
config_routes.set_runtime_apply_callback(reload_runtime_services)


async def resolve_widget_handoff(conversation_id: str, visitor_id: str):
    if handoff_store is None:
        raise HandoffStoreUnavailable("Handoff store is not initialized")
    return await handoff_store.resolve(conversation_id, visitor_id)


set_handoff_resolver(resolve_widget_handoff)


def bearer_token_from_header(value: Optional[str]) -> Optional[str]:
    """Extract a bearer token without accepting alternate authorization schemes."""
    if not value:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_widget_request_token(
    request: Request,
    conversation_id: str,
    chatwoot_conversation_id: str,
) -> None:
    """Require a widget capability bound to both public and Chatwoot IDs."""
    token = bearer_token_from_header(request.headers.get("authorization"))
    if not token:
        raise HTTPException(status_code=401, detail="Widget capability token required")
    try:
        validate_widget_token(token, conversation_id, str(chatwoot_conversation_id))
    except WidgetScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TokenValidationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Authentication is not configured") from exc


async def receive_websocket_auth_token(websocket: WebSocket) -> Optional[str]:
    """Accept a socket and require an auth frame within five seconds."""
    await websocket.accept()
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, TypeError):
        await websocket.close(code=4401, reason="Authentication required")
        return None
    if not isinstance(frame, dict) or frame.get("type") != "auth":
        await websocket.close(code=4401, reason="Authentication required")
        return None
    token = frame.get("token")
    if not isinstance(token, str) or not token.strip():
        await websocket.close(code=4401, reason="Authentication required")
        return None
    return token.strip()


class ChatRequest(BaseModel):
    """前端聊天请求"""

    message: str = Field(..., min_length=1, description="用户消息内容")
    conversation_id: str = Field("web-visitor", description="前端会话 ID")
    user_id: str = Field("web-user", description="访客或用户 ID")


class SendReplyRequest(BaseModel):
    """客服回复请求"""

    content: str = Field(..., min_length=1, description="回复内容")
    private: bool = Field(False, description="是否内部备注")


class AssignConversationRequest(BaseModel):
    """分配会话请求"""

    assignee_id: Optional[int] = Field(None, description="Chatwoot 坐席 ID")


class LabelsUpdateRequest(BaseModel):
    """更新标签请求"""

    labels: list[str] = Field(default_factory=list, description="完整标签列表")


class StatusUpdateRequest(BaseModel):
    """更新状态请求"""

    status: str = Field(..., description="open/pending/resolved/snoozed")






@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global chatwoot, dify, intent_analyzer, cache, handoff_store, webhook_idempotency

    # 启动时初始化服务
    logger.info("初始化 Bridge Service...")
    runtime = config_manager.get_all() if config_manager.get("setup.initialized", False) else None
    chatwoot_config = _runtime_chatwoot_config(runtime)
    runtime_rules = _runtime_ai_rules(runtime)
    runtime_rules["confidence_threshold"] = float(runtime_rules["confidence_threshold"])
    runtime_rules["handoff_keywords"] = list(runtime_rules["handoff_keywords"])
    chatwoot = ChatwootService(
        base_url=chatwoot_config["base_url"],
        api_token=chatwoot_config["api_token"],
        account_id=chatwoot_config["account_id"],
    )
    dify = DifyService(
        api_url=settings.dify_api_url,
        api_key=settings.dify_api_key
    )
    intent_analyzer = IntentAnalyzer()

    # 标准版只初始化本地 AI；Dify 增强版必须显式设置 AI_PROVIDER=dify。
    global ai_engine
    if settings.ai_provider == "local":
        try:
            ai_engine = await _create_ai_engine(runtime)
            logger.info("本地 AI 引擎初始化完成")
        except Exception as e:
            logger.error(f"本地 AI 引擎初始化失败: {e}")
            ai_engine = None
    else:
        ai_engine = None
        logger.info("Dify 增强模式已启用，本地 AI 引擎不参与消息处理")
    set_ai_engine(ai_engine)
    _apply_effective_runtime_settings(chatwoot_config, runtime_rules)

    # 初始化 Redis 缓存（可选）
    cache_ready = False
    try:
        cache = RedisCache(
            host=getattr(settings, 'redis_host', 'localhost'),
            port=getattr(settings, 'redis_port', 6379),
            password=getattr(settings, 'redis_password', None),
            db=getattr(settings, 'redis_db', 0)
        )
        if await cache.ping():
            cache_ready = True
            logger.info("Redis 缓存连接成功")
        else:
            logger.warning("Redis 缓存连接失败，将不使用缓存功能")
            await cache.close()
            cache = None
    except Exception as e:
        logger.warning(f"Redis 初始化失败: {str(e)}，将不使用缓存功能")
        cache = None

    configure_session_store(cache.client if cache_ready and cache else None)
    handoff_store = HandoffStore(
        cache.client if cache_ready and cache else None,
        fingerprint_secret=jwt_secret(),
    )
    webhook_idempotency = WebhookIdempotency(
        cache.client if cache_ready and cache else None,
        lock_seconds=settings.webhook_idempotency_lock_seconds,
        done_seconds=settings.webhook_idempotency_done_seconds,
    )
    set_handoff_resolver(resolve_widget_handoff)

    logger.info("Bridge Service 启动成功")

    yield

    # 关闭时清理资源
    logger.info("关闭 Bridge Service...")
    await chatwoot.close()
    await dify.close()
    if cache:
        await cache.close()
    if ai_engine:
        await ai_engine.close()
    logger.info("Bridge Service 已关闭")


app = FastAPI(
    title="AI Customer Service Bridge",
    description="Chatwoot、本地 AI 与可选 Dify 的统一桥接服务",
    version="1.0.0",
    lifespan=lifespan
)

def current_cors_origins() -> set[str]:
    configured = {
        item.strip().rstrip("/")
        for item in str(settings.auth_allowed_origins or "").split(",")
        if item.strip()
    }
    configured.update(
        str(item).strip().rstrip("/")
        for item in config_manager.get("allowed_origins", [])
        if str(item).strip()
    )
    return configured


@app.middleware("http")
async def dynamic_cors(request: Request, call_next):
    """Apply the initialized customer's exact origin allowlist at request time."""
    origin = (request.headers.get("origin") or "").rstrip("/")
    if request.method == "OPTIONS" and origin:
        if origin not in current_cors_origins():
            return Response(status_code=403)
        response = Response(status_code=204)
    else:
        response = await call_next(request)
    if origin and origin in current_cors_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = request.headers.get(
            "access-control-request-headers", "Authorization, Content-Type, X-Site-Token"
        )
        response.headers["Vary"] = "Origin"
    return response


@app.middleware("http")
async def prometheus_metrics(request: Request, call_next):
    return await metrics_middleware(request, call_next)

# 配置限流器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# 挂载 Prometheus 指标端点
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# 挂载路由模块（AI 引擎管理 / 配置管理 / 对话历史 / 知识库 / 管理后台）
app.include_router(ai_management_router)
app.include_router(config_router)
app.include_router(conversations_router)
app.include_router(knowledge_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(widget_router)


@app.get("/")
async def root() -> dict[str, Any]:
    """服务信息端点"""
    return {
        "service": "Bridge Service",
        "version": "1.0.0",
        "description": "企业级 AI 客服桥接服务",
        "tech_stack": "FastAPI + Python 3.11",
        "endpoints": {
            "webhook": "/webhook/chatwoot",
            "chat": "/api/chat",
            "health": "/health",
            "metrics": "/metrics"
        }
    }


@app.websocket("/ws/agent")
async def websocket_agent(websocket: WebSocket) -> None:
    """Agent 工作台实时消息推送端点，使用首帧 access token 认证。"""
    token = await receive_websocket_auth_token(websocket)
    if token is None:
        return
    try:
        claims = decode_token(token, "access")
        if claims.role not in {"agent", "admin"}:
            raise TokenValidationError("Agent role required")
    except (TokenValidationError, AuthConfigurationError):
        await websocket.close(code=4401, reason="Invalid credentials")
        return

    manager.register(websocket, channel="agent")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, channel="agent")


@app.websocket("/ws/widget")
async def websocket_widget(websocket: WebSocket) -> None:
    """访客实时推送端点，能力令牌必须匹配 Chatwoot 会话。"""
    chatwoot_conversation_id = websocket.query_params.get("conversation_id", "")
    token = await receive_websocket_auth_token(websocket)
    if token is None:
        return
    try:
        claims = decode_token(token, "widget")
        validate_widget_token(
            token,
            claims.conversation_id or "",
            chatwoot_conversation_id,
        )
    except (TokenValidationError, AuthConfigurationError):
        await websocket.close(code=4401, reason="Invalid capability")
        return

    channel = f"widget:{chatwoot_conversation_id}"
    manager.register(websocket, channel=channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, channel=channel)


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """健康检查端点，检查服务状态和依赖服务连通性"""
    import time

    uptime_seconds = int(time.time() % 86400)  # 当天运行秒数

    if settings.ai_provider == "local":
        ai_status = "ok" if ai_engine is not None else "unavailable"
        qdrant_url = (
            f"http://{ai_engine.config.qdrant_host}:{ai_engine.config.qdrant_port}"
            if ai_engine is not None else "http://localhost:6333"
        )
        provider_dependencies = {
            "ai_engine": ai_status,
            "qdrant": await probe_dependency(qdrant_url, "qdrant"),
        }
    else:
        dify_health_url = settings.dify_api_url.rstrip('/').removesuffix('/v1') + '/health'
        provider_dependencies = {
            "ai_engine": "not_required",
            "qdrant": "not_required",
            "dify": await probe_dependency(dify_health_url, "dify"),
        }

    dependencies = {
        **provider_dependencies,
        "chatwoot": await probe_dependency(
            f"{settings.chatwoot_base_url.rstrip('/')}/api/v1/accounts/{settings.chatwoot_account_id}/conversations?status=open",
            "chatwoot",
            headers={"api_access_token": settings.chatwoot_api_token},
        ),
    }
    status = "healthy" if all(value in {"ok", "not_required"} for value in dependencies.values()) else "degraded"

    return {
        "status": status,
        "service": "bridge-service",
        "version": "1.0.0",
        "ai_provider": settings.ai_provider,
        "uptime_seconds": uptime_seconds,
        "dependencies": dependencies
    }


async def pick_agent_for_handoff() -> Optional[dict]:
    """选择转人工分配目标：在线客服中最少进行中会话的一个（负载均衡）。

    Returns:
        选中的客服 dict（含 id/name/count），无在线客服时返回 None
    """
    try:
        agents = await chatwoot.list_agents()
        online = []
        for a in agents:
            name = a.get("name") or a.get("available_name") or a.get("email")
            if not name:
                continue
            if await _get_agent_status(name) == "online":
                online.append({"id": a.get("id"), "name": name, "count": 0})

        if not online:
            return None

        # 统计每个在线客服的进行中会话数
        try:
            convs = await chatwoot.list_conversations(status="open")
            payload = convs.get("data", {}).get("payload", [])
            assignee_counts: dict = {}
            for c in payload:
                assignee = (c.get("meta") or {}).get("assignee") or {}
                aid = assignee.get("id") or c.get("assignee_id")
                if aid is not None:
                    assignee_counts[str(aid)] = assignee_counts.get(str(aid), 0) + 1
            for a in online:
                a["count"] = assignee_counts.get(str(a["id"]), 0)
        except Exception as e:
            logger.debug(f"统计客服负载失败（不阻塞）: {e}")

        online.sort(key=lambda a: a["count"])
        return online[0]
    except Exception as e:
        logger.warning(f"选择转人工客服失败: {e}")
        return None


async def auto_assign_waiting_conversations(agent_name: str) -> None:
    """客服上线时，把未分配的待处理转人工会话分配给它（最多一次接管 5 个）。"""
    try:
        agents = await chatwoot.list_agents()
        agent = next(
            (a for a in agents if (a.get("name") or a.get("available_name") or "") == agent_name),
            None,
        )
        if not agent:
            return
        convs = await chatwoot.list_conversations(status="open")
        payload = convs.get("data", {}).get("payload", [])
        assigned = 0
        for c in payload:
            if assigned >= 5:
                break
            labels = c.get("labels") or []
            assignee = (c.get("meta") or {}).get("assignee") or {}
            if assignee.get("id") is not None:
                continue  # 已分配
            if "needs_human" in labels or "waiting" in labels:
                try:
                    await chatwoot.assign_conversation(str(c.get("id")), assignee_id=agent.get("id"))
                    assigned += 1
                except Exception:
                    pass
        if assigned:
            logger.info(f"客服 {agent_name} 上线，自动接管 {assigned} 个等待会话")
    except Exception as e:
        logger.warning(f"自动分配等待会话失败: {e}")


async def _sync_history_context(
    chat_conversation_id: str,
    chatwoot_conv_id: str,
    current_message: str,
) -> None:
    """将 AI 对话历史同步到 Chatwoot 会话，让人工客服看到转人工前的上下文。

    - 访客消息 → incoming（归属访客）
    - AI 回复   → outgoing + private（仅客服可见的内部备注，避免当作客服已回复）
    - 跳过触发转人工的那条消息（execute_handoff 会单独补发），避免重复。
    任何失败都不阻塞转人工主流程。
    """
    if cache is None:
        return
    try:
        raw = await cache.get(f"conversation:{chat_conversation_id}")
    except Exception as e:
        logger.warning(f"读取会话历史失败（跳过上下文同步）: {e}")
        return
    if not raw:
        return
    try:
        history = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return
    if not isinstance(history, list):
        return

    # 只同步当前消息之前的上下文（取最后一次匹配位置，避免历史中重复问题被截断）
    cutoff = len(history)
    for i, item in enumerate(history):
        if item.get("role") == "user" and item.get("content") == current_message:
            cutoff = i

    for item in history[:cutoff]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        try:
            if role == "user":
                await chatwoot.send_message(
                    conversation_id=chatwoot_conv_id,
                    content=content,
                    message_type="incoming",
                )
            elif role == "assistant":
                await chatwoot.send_message(
                    conversation_id=chatwoot_conv_id,
                    content=f"🤖 AI 回复：{content}",
                    message_type="outgoing",
                    private=True,
                )
        except Exception as e:
            logger.warning(f"同步历史消息失败（不阻塞）: {e}")


async def execute_handoff(
    chat_message: str,
    chat_user_id: str,
    chat_conversation_id: str,
) -> dict:
    """执行转人工：在 Chatwoot 创建会话、加标签、分配客服。

    Returns:
        转人工结果 dict，失败时 ok=False
    """
    try:
        inbox_id = settings.chatwoot_inbox_id

        # 1. 创建访客联系人（用 source_id 标识同一访客；重复时 Chatwoot 会 500，追加后缀重试）
        visitor_name = f"访客{chat_user_id[-8:]}" if chat_user_id else "访客"
        source_id = chat_user_id or f"conv-{chat_conversation_id}"
        contact = None
        for attempt in range(2):
            try:
                contact = await chatwoot.create_contact(
                    name=visitor_name,
                    inbox_id=inbox_id,
                    source_id=source_id,
                )
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"创建联系人冲突，追加后缀重试: {e}")
                    source_id = f"{source_id}-{int(time.time() * 1000) % 100000}"
                else:
                    raise

        # Chatwoot 联系人响应结构为 {"payload": {"contact": {id}, "contact_inboxes": [...]}}
        contact_id = (
            contact.get("id")
            or (contact.get("payload") or {}).get("contact", {}).get("id")
            or (contact.get("payload") or {}).get("id")
        )
        if not contact_id:
            raise RuntimeError(f"无法获取联系人 ID: {contact}")

        # 2. 通过 API 渠道创建空会话
        conv = await chatwoot.create_conversation(
            inbox_id=inbox_id,
            contact_id=contact_id,
        )
        conv_id = str(
            conv.get("id")
            or (conv.get("payload") or {}).get("id")
            or (conv.get("data") or {}).get("id")
        )
        if not conv_id:
            raise RuntimeError(f"无法获取会话 ID: {conv}")

        # 2.4 同步 AI 对话上下文到 Chatwoot（客服可看到转人工前的问题与 AI 答复）
        try:
            await _sync_history_context(
                chat_conversation_id=chat_conversation_id,
                chatwoot_conv_id=conv_id,
                current_message=chat_message,
            )
        except Exception as e:
            logger.warning(f"同步历史上下文失败（不阻塞）: {e}")

        # 2.5 补发访客原始消息（message_type=incoming → Chatwoot 归属到 contact/访客）
        try:
            await chatwoot.send_message(
                conversation_id=conv_id,
                content=chat_message,
                message_type="incoming",
            )
        except Exception as e:
            logger.warning(f"补发访客消息失败（不阻塞）: {e}")

        # 2.6 原子记录路由和访客绑定；失败时不能签发不可恢复的人工会话令牌。
        if handoff_store is None:
            raise HandoffStoreUnavailable("Handoff store is not initialized")
        await handoff_store.save(
            chat_conversation_id,
            chat_user_id,
            conv_id,
        )

        # 3. 添加 needs_human 标签（标签不存在则先创建）
        try:
            await chatwoot.create_label("needs_human")
            await chatwoot.set_labels(conv_id, ["needs_human"])
        except Exception as e:
            logger.warning(f"转人工标签设置失败（不阻塞）: {e}")

        # 4. 负载均衡分配：选择在线客服中最少进行中会话的一个
        assigned = False
        target = await pick_agent_for_handoff()
        if target:
            try:
                await chatwoot.assign_conversation(conv_id, assignee_id=target["id"])
                assigned = True
                logger.info(f"转人工已分配给 {target['name']}（当前 {target['count']} 个会话）")
            except Exception as e:
                logger.warning(f"转人工分配客服失败（不阻塞）: {e}")

        # 4.5 无在线客服：排队等待，标记 waiting，客服上线后自动分配
        if not assigned:
            try:
                await chatwoot.create_label("waiting")
                await chatwoot.set_labels(conv_id, ["needs_human", "waiting"])
            except Exception:
                pass

        logger.info(f"转人工成功: Chatwoot会话 {conv_id}, 访客 {chat_user_id}, 已分配={assigned}")
        handoff_counter.labels(reason="keyword", result="success").inc()
        capability_token, _ = create_widget_token(chat_conversation_id, str(conv_id))
        return {
            "ok": True,
            "conversation_id": conv_id,
            "capability_token": capability_token,
            "assigned": assigned,
            "reply": "已为您转接人工客服，客服将尽快回复您～🙋",
        }
    except Exception as e:
        handoff_counter.labels(reason="keyword", result="error").inc()
        logger.error(f"转人工执行失败: {e}", exc_info=True)
        return {
            "ok": False,
            "reply": "转人工暂时不可用，请稍后再试，或致电 400-999-8888 联系客服。",
        }


@app.post("/api/chat")
@limiter.limit("30/minute")  # 每分钟最多30次请求
async def chat_endpoint(
    request: Request,
    payload: Optional[ChatRequest] = Body(None),
    message: Optional[str] = Query(None),
    conversation_id: str = Query("test_conv"),
    user_id: str = Query("test_user")
) -> dict[str, Any]:
    """直接聊天接口，支持前端 JSON 请求并兼容旧 query 调用。"""
    import time

    chat_message = payload.message if payload else message
    chat_conversation_id = payload.conversation_id if payload else conversation_id
    chat_user_id = payload.user_id if payload else user_id

    if not chat_message or not chat_message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    start_time = time.time()
    message_result = "error"

    try:
        # 转人工模式：该访客会话已转人工，消息直接转发给 Chatwoot 人工客服
        try:
            if handoff_store is None:
                raise HandoffStoreUnavailable("Handoff store is not initialized")
            handoff_conv_id = await handoff_store.get_chatwoot_conversation_id(
                chat_conversation_id
            )
        except HandoffStoreUnavailable as exc:
            if setup_service.is_initialized():
                raise HTTPException(
                    status_code=503,
                    detail={"code": "HANDOFF_STORE_UNAVAILABLE"},
                ) from exc
            handoff_conv_id = None
        if handoff_conv_id:
            require_widget_request_token(
                request,
                chat_conversation_id,
                str(handoff_conv_id),
            )
            try:
                await chatwoot.send_message(
                    conversation_id=handoff_conv_id,
                    content=chat_message,
                    message_type="incoming",
                )
                # 通知客服工作台有新的访客消息
                await manager.broadcast(
                    {
                        "type": "conversation_message",
                        "conversation_id": handoff_conv_id,
                        "sender": "visitor",
                        "content": chat_message,
                    },
                    channel="agent",
                )
                message_result = "success"
                return {
                    "reply": "已发送给人工客服，请稍候～",
                    "intent": "handoff",
                    "confidence": 0.0,
                    "conversation_id": chat_conversation_id,
                    "response_time_ms": int((time.time() - start_time) * 1000),
                    "ok": True,
                    "handoff": {"ok": True, "conversation_id": handoff_conv_id},
                }
            except Exception as e:
                logger.error(f"转人工消息转发失败: {e}", exc_info=True)
                return {
                    "reply": "消息发送失败，请稍后再试。",
                    "intent": "error",
                    "confidence": 0.0,
                    "conversation_id": chat_conversation_id,
                    "response_time_ms": int((time.time() - start_time) * 1000),
                    "ok": False,
                }

        # Once setup is complete, every normal widget message must carry the
        # short-lived capability issued by /api/widget/session.
        if setup_service.is_initialized():
            token = bearer_token_from_header(request.headers.get("authorization"))
            if not token:
                raise HTTPException(status_code=401, detail="Widget session token required")
            try:
                validate_widget_session_token(token, chat_conversation_id, widget_site_id())
            except WidgetScopeError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            except TokenValidationError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            except AuthConfigurationError as exc:
                raise HTTPException(status_code=503, detail="Authentication is not configured") from exc

        # 意图识别
        intent_result = intent_analyzer.analyze(chat_message)

        ai_response = await request_ai_response(
            message=chat_message,
            user_id=chat_user_id,
            conversation_id=chat_conversation_id,
        )

        response_time_ms = int((time.time() - start_time) * 1000)

        # 转人工执行：识别到需要人工时，在 Chatwoot 创建真实客服会话
        handoff_info = None
        if intent_result.requires_human:
            handoff_info = await execute_handoff(
                chat_message=chat_message,
                chat_user_id=chat_user_id,
                chat_conversation_id=chat_conversation_id,
            )
            # 转人工成功则覆盖回复，告知访客已转接
            if handoff_info and handoff_info.get("ok"):
                ai_response = AIResponse(
                    text=handoff_info.get("reply", ai_response.text),
                    confidence=ai_response.confidence,
                    metadata={},
                )

        message_result = "success"
        return {
            "reply": ai_response.text,
            "intent": intent_result.intent,
            "confidence": ai_response.confidence,
            "conversation_id": chat_conversation_id,
            "response_time_ms": response_time_ms,
            "ok": ai_response.confidence > 0,
            "handoff": handoff_info,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天接口错误: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="AI 服务暂时不可用")
    finally:
        message_counter.labels(source="widget", result=message_result).inc()


@app.get("/api/chat/handoff")
@limiter.limit("120/minute")
async def get_handoff_messages(request: Request, conversation_id: str = Query("test_conv")) -> dict[str, Any]:
    """访客 widget 轮询：返回转人工会话中的人工客服回复（含访客消息）。

    访客在前端本地已显示自己发送的消息，因此这里同时返回全部消息，
    由前端按 id 去重追加。
    """
    try:
        if handoff_store is None:
            raise HandoffStoreUnavailable("Handoff store is not initialized")
        chatwoot_conv_id = await handoff_store.get_chatwoot_conversation_id(
            conversation_id
        )
        if not chatwoot_conv_id:
            return {"handoff": False, "messages": []}

        require_widget_request_token(request, conversation_id, str(chatwoot_conv_id))

        # 获取 Chatwoot 会话全部消息并映射为前端格式
        data = await chatwoot.get_messages(chatwoot_conv_id)
        raw_messages = data.get("payload", []) if isinstance(data, dict) else (data or [])
        messages = []
        for m in raw_messages:
            # 过滤活动/系统消息（type=2 activity）
            if m.get("message_type") == 2 or (m.get("content") or "").strip() == "":
                continue
            messages.append(map_chatwoot_message(m))

        return {"handoff": True, "conversation_id": chatwoot_conv_id, "messages": messages}
    except HTTPException:
        raise
    except HandoffStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "HANDOFF_STORE_UNAVAILABLE"},
        ) from exc
    except Exception as e:
        logger.error(f"获取转人工会话消息失败: {e}", exc_info=True)
        return {"handoff": False, "messages": [], "error": str(e)}


async def probe_dependency(url: str, name: str, headers: Optional[dict[str, str]] = None) -> str:
    """轻量探测依赖是否可达，避免健康检查返回假 ok。"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code < 500:
            return "ok"
        return f"error:{response.status_code}"
    except Exception as e:
        logger.warning(f"{name} 健康检查失败: {e}")
        return "unreachable"


@app.get("/api/agent/conversations", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def list_agent_conversations(request: Request, status: str = Query("open")) -> dict[str, Any]:
    """获取 Chatwoot 真实会话列表。"""
    try:
        data = await chatwoot.list_conversations(status=status)
        payload = data.get("data", {}).get("payload", [])
        meta = data.get("data", {}).get("meta", {})
        return {
            "conversations": [map_chatwoot_conversation(item) for item in payload],
            "meta": meta,
        }
    except Exception as e:
        logger.error(f"获取客服会话列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法获取 Chatwoot 会话列表")


@app.get("/api/agent/conversations/{conversation_id}", dependencies=[Depends(require_agent)])
@limiter.limit("120/minute")
async def get_agent_conversation(request: Request, conversation_id: str) -> dict[str, Any]:
    """获取 Chatwoot 真实会话详情和消息。"""
    try:
        conversation_data = await chatwoot.get_conversation(conversation_id)
        messages_data = await chatwoot.get_messages(conversation_id)
        message_payload = messages_data.get("payload", conversation_data.get("messages", []))
        return {
            "conversation": map_chatwoot_conversation(conversation_data),
            "messages": [map_chatwoot_message(item) for item in message_payload],
        }
    except Exception as e:
        logger.error(f"获取客服会话详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法获取 Chatwoot 会话详情")


async def _agent_status_key(name: str) -> str:
    """客服状态 Redis 键。"""
    return f"agent_status:{name}"


async def _get_agent_status(name: str) -> str:
    """读取客服状态（Redis 优先，缺省 offline）。"""
    if cache is None:
        return "offline"
    try:
        value = await cache.get(await _agent_status_key(name))
        return value if value in {"online", "away", "busy", "offline"} else "offline"
    except Exception:
        return "offline"


@app.get("/api/agent/agents", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def list_agent_users(request: Request) -> dict[str, Any]:
    """获取坐席列表（合并 Redis 在线状态）。"""
    try:
        agents = await chatwoot.list_agents()
        result = []
        for agent in agents:
            name = agent.get("name") or agent.get("available_name") or agent.get("email") or f"Agent {agent.get('id')}"
            result.append({
                "id": str(agent.get("id")),
                "chatwootId": agent.get("id"),
                "name": name,
                "status": await _get_agent_status(name),
                "role": agent.get("role"),
            })
        return {"agents": result}
    except Exception as e:
        logger.error(f"获取坐席列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法获取 Chatwoot 坐席列表")


class AgentStatusRequest(BaseModel):
    """客服状态请求"""
    username: str = Field(..., min_length=1, description="客服用户名")
    status: str = Field(..., description="online/away/busy/offline")


@app.put("/api/agent/status", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def update_agent_status(request: Request, payload: AgentStatusRequest) -> dict[str, Any]:
    """更新客服在线/忙闲状态（Redis 存储，供转人工分配路由使用）。"""
    valid = {"online", "away", "busy", "offline"}
    if payload.status not in valid:
        raise HTTPException(status_code=400, detail="无效状态，可选: online/away/busy/offline")
    if cache is None:
        raise HTTPException(status_code=502, detail="缓存不可用")

    try:
        await cache.set(await _agent_status_key(payload.username), payload.status, expire=86400 * 30)
        logger.info(f"客服 {payload.username} 状态更新为 {payload.status}")

        # 客服上线时，尝试分配等待中的转人工会话
        if payload.status == "online":
            await auto_assign_waiting_conversations(payload.username)

        return {"status": payload.status, "username": payload.username}
    except Exception as e:
        logger.error(f"更新客服状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新状态失败")


@app.get("/api/agent/labels", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def list_agent_labels(request: Request) -> dict[str, Any]:
    """获取 Chatwoot 标签列表。"""
    try:
        labels_data = await chatwoot.list_labels()
        labels = labels_data.get("payload", labels_data if isinstance(labels_data, list) else [])
        return {"labels": labels}
    except Exception as e:
        logger.error(f"获取标签列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法获取 Chatwoot 标签列表")


@app.post("/api/agent/conversations/{conversation_id}/messages", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def send_agent_reply(
    request: Request,
    conversation_id: str,
    payload: SendReplyRequest,
) -> dict[str, Any]:
    """发送客服回复到 Chatwoot。"""
    try:
        result = await chatwoot.send_message(
            conversation_id=conversation_id,
            content=payload.content,
            message_type="outgoing",
            private=payload.private,
        )
        # 实时推送给访客 widget（channel = widget:{会话id}）
        if not payload.private:
            await manager.broadcast(
                {
                    "type": "agent_reply",
                    "conversation_id": conversation_id,
                    "message": map_chatwoot_message(result),
                },
                channel=f"widget:{conversation_id}",
            )
        return {"message": map_chatwoot_message(result)}
    except Exception as e:
        logger.error(f"发送客服回复失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法发送 Chatwoot 回复")


@app.patch("/api/agent/conversations/{conversation_id}/assignment", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def assign_agent_conversation(
    request: Request,
    conversation_id: str,
    payload: AssignConversationRequest,
) -> dict[str, Any]:
    """分配 Chatwoot 会话。"""
    try:
        # Chatwoot 分配接口返回的是客服对象而非会话对象，统一重新拉取会话详情返回
        await chatwoot.assign_conversation(conversation_id, payload.assignee_id)
        detail = await chatwoot.get_conversation(conversation_id)
        return {"conversation": map_chatwoot_conversation(detail)}
    except Exception as e:
        logger.error(f"分配客服会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法分配 Chatwoot 会话")


class TransferRequest(BaseModel):
    """转接请求"""
    assignee_id: int = Field(..., description="目标客服 Chatwoot ID")
    note: str = Field("", description="转接备注（可选）")


@app.post("/api/agent/conversations/{conversation_id}/transfer", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def transfer_agent_conversation(
    request: Request,
    conversation_id: str,
    payload: TransferRequest,
) -> dict[str, Any]:
    """把会话转接给另一个客服，并追加一条内部备注。"""
    try:
        # 1. 读取当前会话信息（原客服名）
        detail = await chatwoot.get_conversation(conversation_id)
        meta = detail.get("meta") or {}
        old_assignee = (meta.get("assignee") or {}).get("name") or "未分配"

        # 2. 分配给目标客服
        await chatwoot.assign_conversation(conversation_id, payload.assignee_id)
        agents = await chatwoot.list_agents()
        target = next((a for a in agents if a.get("id") == payload.assignee_id), None)
        target_name = target.get("name") or target.get("available_name") or f"客服 {payload.assignee_id}"

        # 3. 追加内部备注（private 消息，仅客服可见）
        note = f"会话由「{old_assignee}」转接给「{target_name}」"
        if payload.note:
            note += f"。备注：{payload.note}"
        await chatwoot.send_message(conversation_id=conversation_id, content=note, message_type="outgoing", private=True)

        # 4. 返回最新会话
        updated = await chatwoot.get_conversation(conversation_id)
        return {"conversation": map_chatwoot_conversation(updated)}
    except Exception as e:
        logger.error(f"转接会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法转接 Chatwoot 会话")


@app.patch("/api/agent/conversations/{conversation_id}/labels", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def update_agent_conversation_labels(
    request: Request,
    conversation_id: str,
    payload: LabelsUpdateRequest,
) -> dict[str, Any]:
    """更新 Chatwoot 会话标签。"""
    try:
        result = await chatwoot.set_labels(conversation_id, payload.labels)
        labels = result.get("payload", payload.labels)
        conversation_data = await chatwoot.get_conversation(conversation_id)
        return {
            "labels": labels,
            "conversation": map_chatwoot_conversation(conversation_data),
        }
    except Exception as e:
        logger.error(f"更新客服会话标签失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法更新 Chatwoot 标签")


@app.patch("/api/agent/conversations/{conversation_id}/status", dependencies=[Depends(require_agent)])
@limiter.limit("60/minute")
async def update_agent_conversation_status(
    request: Request,
    conversation_id: str,
    payload: StatusUpdateRequest,
) -> dict[str, Any]:
    """更新 Chatwoot 会话状态。"""
    if payload.status not in {"open", "pending", "resolved", "snoozed"}:
        raise HTTPException(status_code=400, detail="不支持的会话状态")

    try:
        await chatwoot.update_status(conversation_id, payload.status)
        conversation_data = await chatwoot.get_conversation(conversation_id)
        return {"conversation": map_chatwoot_conversation(conversation_data)}
    except Exception as e:
        logger.error(f"更新客服会话状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法更新 Chatwoot 状态")


def map_chatwoot_conversation(raw: dict[str, Any]) -> dict[str, Any]:
    """将 Chatwoot conversation 转为前端 Conversation。"""
    meta = raw.get("meta") or {}
    sender = meta.get("sender") or meta.get("contact") or {}
    assignee = meta.get("assignee") or {}
    last_message = raw.get("last_non_activity_message") or (raw.get("messages") or [{}])[-1]
    labels = raw.get("labels") or []
    channel = map_channel(meta.get("channel") or raw.get("channel"))

    return {
        "id": str(raw.get("id")),
        "contact": {
            "id": str(sender.get("id") or raw.get("contact_id") or raw.get("id")),
            "name": sender.get("name") or sender.get("email") or f"访客 {raw.get('id')}",
            "avatar": sender.get("thumbnail") or sender.get("avatar_url") or None,
            "email": sender.get("email"),
            "phone": sender.get("phone_number"),
            "channel": channel,
            "attributes": stringify_attributes({
                **(sender.get("custom_attributes") or {}),
                **(sender.get("additional_attributes") or {}),
            }),
        },
        "status": raw.get("status") or "open",
        "priority": raw.get("priority") or "medium",
        "isHandedOff": bool(assignee or raw.get("assignee_id") or "ai_handoff" in labels),
        "assigneeId": str(assignee.get("id") or raw.get("assignee_id")) if (assignee.get("id") or raw.get("assignee_id")) else None,
        "assigneeName": assignee.get("name") or assignee.get("available_name"),
        "labels": labels,
        "lastMessage": last_message.get("content") or raw.get("last_message"),
        "lastMessageAt": timestamp_to_iso(last_message.get("created_at") or raw.get("last_activity_at") or raw.get("timestamp")),
        "unreadCount": raw.get("unread_count") or 0,
        "createdAt": timestamp_to_iso(raw.get("created_at")),
    }


def map_chatwoot_message(raw: dict[str, Any]) -> dict[str, Any]:
    """将 Chatwoot message 转为前端 Message。"""
    sender = raw.get("sender") or {}
    sender_type = map_sender_type(raw)
    content_type = raw.get("content_type") or "text"

    return {
        "id": str(raw.get("id")),
        "conversationId": str(raw.get("conversation_id")),
        "senderType": sender_type,
        "senderName": sender.get("name") or sender.get("available_name"),
        "senderAvatar": sender.get("thumbnail") or sender.get("avatar_url") or None,
        "contentType": content_type if content_type in {"text", "image", "file", "card", "quick_replies"} else "text",
        "content": raw.get("content") or raw.get("processed_message_content") or "",
        "status": raw.get("status") or "sent",
        "createdAt": timestamp_to_iso(raw.get("created_at")),
    }


def map_sender_type(raw: dict[str, Any]) -> str:
    """根据 Chatwoot 字段推断前端消息发送方。"""
    if raw.get("private"):
        return "system"
    sender = raw.get("sender") or {}
    sender_type = (sender.get("type") or raw.get("sender_type") or "").lower()
    message_type = raw.get("message_type")
    if sender_type == "contact" or message_type == 0:
        return "user"
    if sender_type == "user" or message_type == 1:
        return "agent"
    return "system"


def map_channel(channel: Optional[str]) -> str:
    """映射 Chatwoot 渠道到前端渠道枚举。"""
    value = (channel or "").lower()
    if "wechat" in value:
        return "wechat"
    if "whatsapp" in value:
        return "whatsapp"
    if "api" in value or "app" in value:
        return "app"
    return "web"


def timestamp_to_iso(value: Any) -> str:
    """转换 Chatwoot 时间戳/字符串为 ISO 字符串。"""
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


def stringify_attributes(attributes: dict[str, Any]) -> dict[str, str]:
    """前端联系人自定义属性需要字符串值。"""
    result: dict[str, str] = {}
    for key, value in attributes.items():
        if value is None or isinstance(value, (dict, list)):
            continue
        result[str(key)] = str(value)
    return result


@app.post("/webhook/chatwoot")
@limiter.limit("180/minute")  # 为 Adapter 的持续负载、突发和短时重试预留容量
async def chatwoot_webhook(request: Request) -> dict[str, Any]:
    """接收 Chatwoot Webhook 事件

    Args:
    Returns:
        处理结果
    """
    event_label = "other"
    claim_owner: str | None = None
    event_id: str | None = None
    try:
        payload = await request.body()
        signature = request.headers.get("X-Chatwoot-Signature")
        timestamp = request.headers.get("X-Chatwoot-Timestamp")
        signature_version = request.headers.get("X-Chatwoot-Signature-Version")
        event_id = request.headers.get("X-Chatwoot-Event-Id")

        if is_production() and not settings.chatwoot_webhook_secret:
            raise HTTPException(
                status_code=503,
                detail="Chatwoot webhook authentication is not configured",
            )
        if not await verify_webhook_signature(
            signature,
            payload,
            timestamp,
            version=signature_version,
            event_id=event_id,
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        try:
            webhook = ChatwootWebhook.model_validate_json(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(include_input=False),
            ) from exc

        async def finish(result: dict[str, Any]) -> dict[str, Any]:
            nonlocal claim_owner
            if claim_owner and event_id and webhook_idempotency:
                try:
                    await webhook_idempotency.complete(event_id, claim_owner)
                except WebhookIdempotencyUnavailable as exc:
                    raise HTTPException(
                        status_code=503,
                        detail="Webhook idempotency store is unavailable",
                    ) from exc
                claim_owner = None
                webhook_idempotency_total.labels(result="completed").inc()
            return result

        if signature_version == "v2":
            if webhook_idempotency is None or event_id is None:
                raise HTTPException(
                    status_code=503,
                    detail="Webhook idempotency store is unavailable",
                )
            try:
                claim = await webhook_idempotency.claim(event_id)
            except WebhookIdempotencyUnavailable as exc:
                webhook_idempotency_total.labels(result="unavailable").inc()
                raise HTTPException(
                    status_code=503,
                    detail="Webhook idempotency store is unavailable",
                ) from exc
            webhook_idempotency_total.labels(result=claim.status).inc()
            if claim.status == "duplicate":
                return {"status": "duplicate"}
            if claim.status == "in_progress":
                raise HTTPException(status_code=409, detail={"status": "in_progress"})
            claim_owner = claim.owner

        logger.info(f"收到 Chatwoot Webhook: {webhook.event}")
        event_label = normalize_webhook_event(webhook.event)

        # 只处理新消息事件
        if webhook.event != 'message_created':
            logger.debug(f"忽略事件: {webhook.event}")
            webhook_counter.labels(event=event_label, result="ignored").inc()
            return await finish({"status": "ignored", "reason": "not_message_created"})

        # 验证消息和会话数据
        if not webhook.message or not webhook.conversation:
            logger.warning("消息或会话数据缺失")
            webhook_counter.labels(event=event_label, result="invalid").inc()
            return await finish({"status": "error", "reason": "missing_data"})

        # 过滤机器人自己的消息和私有消息
        if webhook.message.message_type == 'outgoing' or webhook.message.private:
            logger.debug("忽略系统消息或私有消息")
            webhook_counter.labels(event=event_label, result="ignored").inc()
            return await finish({"status": "ignored", "reason": "outgoing_or_private"})

        # 提取关键信息
        conversation_id = str(webhook.conversation.id)
        user_message = webhook.message.content.strip()
        sender_id = str(webhook.message.sender.id) if webhook.message.sender else 'unknown'

        if not user_message:
            logger.warning("消息内容为空")
            webhook_counter.labels(event=event_label, result="invalid").inc()
            return await finish({"status": "error", "reason": "empty_message"})

        # 异步处理消息并获取结果（失败不返回 500，避免 Chatwoot 判定失败导致消息丢失）
        try:
            result = await process_message(
                conversation_id=conversation_id,
                user_message=user_message,
                sender_id=sender_id,
                conversation_data={"id": webhook.conversation.id, "status": webhook.conversation.status}
            )
        except Exception as e:
            logger.error(f"消息处理失败，会话已保留（客服可人工处理）: {e}", exc_info=True)
            webhook_counter.labels(event=event_label, result="processing_failed").inc()
            message_counter.labels(source="chatwoot", result="error").inc()
            return await finish({"status": "accepted", "reason": "processing_failed", "conversation_id": conversation_id})

        webhook_counter.labels(event=event_label, result="success").inc()
        message_counter.labels(source="chatwoot", result="success").inc()

        # 返回详细的响应信息
        return await finish({
            "status": "success",
            "conversation_id": int(conversation_id),
            "message_id": webhook.message.id,
            "action": result["action"],
            "intent": result["intent"],
            "confidence": result["confidence"],
            "response_time_ms": result["response_time_ms"],
            **({"reason": result["reason"]} if "reason" in result else {})
        })

    except HTTPException:
        if claim_owner and event_id and webhook_idempotency:
            try:
                await webhook_idempotency.release(event_id, claim_owner)
                webhook_idempotency_total.labels(result="released").inc()
            except WebhookIdempotencyUnavailable:
                logger.error("Webhook idempotency lock release failed")
        webhook_counter.labels(event=event_label, result="rejected").inc()
        raise
    except Exception as e:
        if claim_owner and event_id and webhook_idempotency:
            try:
                await webhook_idempotency.release(event_id, claim_owner)
                webhook_idempotency_total.labels(result="released").inc()
            except WebhookIdempotencyUnavailable:
                logger.error("Webhook idempotency lock release failed")
        webhook_counter.labels(event=event_label, result="error").inc()
        logger.error(f"处理 Webhook 失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def process_message(
    conversation_id: str,
    user_message: str,
    sender_id: str,
    conversation_data: dict[str, Any]
) -> dict[str, Any]:
    """处理用户消息的核心逻辑

    Args:
        conversation_id: Chatwoot 会话 ID
        user_message: 用户消息内容
        sender_id: 发送者 ID
        conversation_data: 会话元数据

    Returns:
        处理结果，包含 action, intent, confidence 等信息
    """
    import time
    start_time = time.time()

    logger.info(f"处理消息 - 会话: {conversation_id}, 用户: {sender_id}")

    # 实时推送新消息给前端（WebSocket）
    await manager.broadcast({
        "type": "new_message",
        "conversation_id": conversation_id,
        "content": user_message[:100],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # 0. 检查会话状态（如果启用了缓存）
    unresolved_count = 0
    if cache:
        state = await cache.get_conversation_state(conversation_id)
        if state:
            unresolved_count = state.unresolved_count
            logger.info(f"会话 {conversation_id} 当前未解决次数: {unresolved_count}")

    # 1. 意图识别
    intent_result: IntentResult = intent_analyzer.analyze(user_message)
    logger.info(f"意图识别结果: {intent_result.intent}, 需要人工: {intent_result.requires_human}")

    # 2. 如果需要立即转人工
    if intent_result.requires_human:
        await handoff_to_human(conversation_id, intent_result.reason)
        response_time_ms = int((time.time() - start_time) * 1000)
        return {
            "action": "transferred_to_human",
            "intent": intent_result.intent,
            "confidence": 0.0,
            "reason": intent_result.reason,
            "response_time_ms": response_time_ms
        }

    # 3. 检查问答缓存（如果启用）
    cached_answer = None
    if cache:
        cached_answer = await cache.get_cached_answer(user_message)
        if cached_answer:
            logger.info("使用缓存的答案")
            # 发送缓存的答案
            await chatwoot.send_message(
                conversation_id=conversation_id,
                content=cached_answer,
                message_type='outgoing',
                private=False
            )
            # 重置未解决计数
            if cache:
                await cache.reset_unresolved(conversation_id)

            response_time_ms = int((time.time() - start_time) * 1000)
            return {
                "action": "ai_replied",
                "intent": intent_result.intent,
                "confidence": 1.0,  # 缓存答案视为高置信度
                "response_time_ms": response_time_ms,
                "cached": True
            }

    # 4. 调用 AI 获取回复（失败重试一次，避免瞬时故障丢回复）
    ai_response: AIResponse = None
    for _attempt in range(2):
        try:
            ai_response = await request_ai_response(
                message=user_message,
                user_id=sender_id,
                conversation_id=conversation_id,
            )
            break
        except Exception as e:
            if _attempt == 1:
                raise
            logger.warning(f"AI 调用失败，重试一次: {e}")

    logger.info(f"AI 回复获取成功, 置信度: {ai_response.confidence}")

    # 5. 根据置信度判断是否需要转人工
    if ai_response.confidence < settings.confidence_threshold:
        logger.warning(f"AI 置信度过低 ({ai_response.confidence}), 转人工处理")

        # 递增未解决计数
        if cache:
            unresolved_count = await cache.increment_unresolved(conversation_id)
            logger.info(f"递增未解决次数: {unresolved_count}")

        await handoff_to_human(
            conversation_id,
            f"AI 置信度过低: {ai_response.confidence:.2f}"
        )
        # 仍然发送 AI 回复作为参考
        await chatwoot.send_message(
            conversation_id=conversation_id,
            content=f"[AI 参考] {ai_response.text}",
            message_type='outgoing',
            private=True
        )
        response_time_ms = int((time.time() - start_time) * 1000)
        return {
            "action": "transferred_to_human",
            "intent": intent_result.intent,
            "confidence": ai_response.confidence,
            "reason": f"低置信度: {ai_response.confidence:.2f}",
            "response_time_ms": response_time_ms
        }

    # 6. 检查连续未解决次数
    max_unresolved = getattr(settings, 'max_unresolved_count', 3)
    if unresolved_count >= max_unresolved:
        logger.warning(f"连续 {unresolved_count} 次未解决，转人工处理")
        await handoff_to_human(
            conversation_id,
            f"连续 {unresolved_count} 次未能解决问题"
        )
        response_time_ms = int((time.time() - start_time) * 1000)
        return {
            "action": "transferred_to_human",
            "intent": intent_result.intent,
            "confidence": ai_response.confidence,
            "reason": f"连续 {unresolved_count} 次未解决",
            "response_time_ms": response_time_ms
        }

    # 7. 检查回复内容中是否包含转人工关键词
    if should_handoff_by_keywords(ai_response.text):
        logger.info("AI 回复内容触发转人工")
        await handoff_to_human(conversation_id, "AI 回复内容建议转人工")
        response_time_ms = int((time.time() - start_time) * 1000)
        return {
            "action": "transferred_to_human",
            "intent": intent_result.intent,
            "confidence": ai_response.confidence,
            "reason": "AI 回复建议转人工",
            "response_time_ms": response_time_ms
        }

    # 8. 发送 AI 回复给用户
    await chatwoot.send_message(
        conversation_id=conversation_id,
        content=ai_response.text,
        message_type='outgoing',
        private=False
    )

    logger.info(f"AI 回复已发送到会话 {conversation_id}")

    # 9. 缓存高质量答案
    if cache and ai_response.confidence >= 0.9:
        await cache.cache_answer(user_message, ai_response.text)
        logger.debug("缓存高质量答案")

    # 10. 重置未解决计数（因为AI成功回复了）
    if cache:
        await cache.reset_unresolved(conversation_id)

    response_time_ms = int((time.time() - start_time) * 1000)
    return {
        "action": "ai_replied",
        "intent": intent_result.intent,
        "confidence": ai_response.confidence,
        "response_time_ms": response_time_ms
    }


async def handoff_to_human(conversation_id: str, reason: str) -> None:
    """转接到人工客服

    Args:
        conversation_id: Chatwoot 会话 ID
        reason: 转人工原因
    """
    logger.info(f"转人工处理 - 会话: {conversation_id}, 原因: {reason}")

    try:
        # 1. 添加标签标识需要人工
        await chatwoot.add_label(conversation_id, 'needs_human')
        await chatwoot.add_label(conversation_id, 'ai_handoff')

        # 2. 发送私有备注（内部可见）
        note_content = f"🤖 AI 自动转人工\n原因: {reason}\n时间: {import_datetime_now()}"
        await chatwoot.send_message(
            conversation_id=conversation_id,
            content=note_content,
            message_type='outgoing',
            private=True
        )

        # 3. 分配给客服（自动分配）
        await chatwoot.assign_conversation(conversation_id, assignee_id=None)

        # 4. 记录转人工指标
        handoff_counter.labels(reason=normalize_handoff_reason(reason), result="success").inc()

        logger.info(f"会话 {conversation_id} 已成功转人工")

    except Exception as e:
        handoff_counter.labels(reason=normalize_handoff_reason(reason), result="error").inc()
        logger.error(f"转人工失败: {str(e)}", exc_info=True)
        # 即使转人工失败，也不抛出异常，避免影响主流程


def should_handoff_by_keywords(text: str) -> bool:
    """检查文本是否包含需要转人工的关键词

    Args:
        text: 待检查的文本内容

    Returns:
        是否需要转人工
    """
    if not text:
        return False

    text_lower = text.lower().strip()
    handoff_triggers = [
        '转人工',
        '人工客服',
        '联系客服',
        '无法回答',
        '不确定',
        '建议咨询',
        '需要进一步'
    ]

    for keyword in handoff_triggers:
        if keyword in text_lower:
            logger.debug(f"检测到转人工触发词: '{keyword}'")
            return True

    return False


def import_datetime_now() -> str:
    """获取当前时间字符串（避免顶层导入循环依赖）

    Returns:
        格式化的当前时间
    """
    from datetime import datetime
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
