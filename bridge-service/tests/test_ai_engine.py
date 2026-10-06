"""AIEngine 单元测试"""
import pytest
from unittest.mock import AsyncMock
from src.services.ai_engine import AIEngine


@pytest.fixture
def engine():
    """构造 AIEngine 并 mock 外部依赖（embedding/向量库/LLM）"""
    e = AIEngine()
    e.embedding = AsyncMock()
    e.vector_store = AsyncMock()
    e.llm = AsyncMock()
    e._redis = None  # 单元测试禁用 Redis 持久化，测纯逻辑
    return e


# ==================== chat ====================

@pytest.mark.asyncio
async def test_chat_success_with_rag(engine):
    """RAG 命中时返回知识增强回复"""
    engine.embedding.embed = AsyncMock(return_value=[0.1] * 512)
    engine.vector_store.search = AsyncMock(return_value=[
        {"text": "营业时间9-18点", "score": 0.8, "metadata": {"source": "faq.json"}},
    ])
    engine.llm.chat_completion = AsyncMock(return_value={
        "choices": [{"message": {"content": "我们的营业时间是9:00-18:00"}}]
    })

    resp = await engine.chat("营业时间是什么？", "c1", "u1")

    assert resp.reply == "我们的营业时间是9:00-18:00"
    assert resp.intent == "inquiry"
    assert resp.confidence > 0.5
    assert len(resp.sources) == 1


@pytest.mark.asyncio
async def test_chat_rag_skipped_on_embedding_failure(engine):
    """embedding 失败时跳过 RAG，仍返回回复"""
    engine.embedding.embed = AsyncMock(side_effect=Exception("embedding down"))
    engine.llm.chat_completion = AsyncMock(return_value={
        "choices": [{"message": {"content": "你好！"}}]
    })

    resp = await engine.chat("你好", "c1", "u1")

    assert resp.reply == "你好！"
    # 无检索时置信度 0.3
    assert resp.confidence == 0.3


@pytest.mark.asyncio
async def test_chat_error_returns_fallback(engine):
    """LLM 异常时返回降级回复"""
    engine.embedding.embed = AsyncMock(return_value=[0.1] * 512)
    engine.vector_store.search = AsyncMock(return_value=[])
    engine.llm.chat_completion = AsyncMock(side_effect=Exception("LLM down"))

    resp = await engine.chat("你好", "c1", "u1")

    assert resp.intent == "error"
    assert "抱歉" in resp.reply
    assert resp.confidence == 0.0


# ==================== 意图识别 ====================

def test_analyze_intent_handoff(engine):
    assert engine._analyze_intent("我要投诉") == "handoff"


def test_analyze_intent_handoff_refund(engine):
    assert engine._analyze_intent("我想退款") == "handoff"


def test_analyze_intent_greeting(engine):
    assert engine._analyze_intent("你好") == "greeting"


def test_analyze_intent_inquiry(engine):
    assert engine._analyze_intent("怎么登录账户？") == "inquiry"


def test_analyze_intent_handoff_precedes_inquiry(engine):
    """转人工关键词优先级高于咨询（如 '退款'）"""
    assert engine._analyze_intent("怎么退款？") == "handoff"


def test_analyze_intent_general(engine):
    assert engine._analyze_intent("随便聊聊") == "general"


# ==================== 消息构建 ====================

def test_build_messages_with_knowledge(engine):
    messages = engine._build_messages("营业时间", [{"text": "9-18点"}], "c1")
    system = messages[0]["content"]
    assert "9-18点" in system
    # 最后一条是用户消息
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "营业时间"


def test_build_messages_without_knowledge(engine):
    messages = engine._build_messages("你好", [], "c1")
    assert "知识库参考内容" not in messages[0]["content"]


# ==================== 置信度 ====================

def test_calculate_confidence_no_results(engine):
    assert engine._calculate_confidence([], "回复") == 0.3


def test_calculate_confidence_with_results(engine):
    # 0.8*0.7 + (2/3)*0.3 = 0.56 + 0.2 = 0.76
    c = engine._calculate_confidence([{"score": 0.8}, {"score": 0.7}], "正常回复")
    assert c == 0.76


def test_calculate_confidence_uncertain_word(engine):
    # (0.8*0.7 + (1/3)*0.3) * 0.7 = 0.66 * 0.7 = 0.46
    c = engine._calculate_confidence([{"score": 0.8}], "我不确定这个")
    assert c == 0.46
