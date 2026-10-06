"""IntentAnalyzer 单元测试"""
import pytest
from src.services.intent import IntentAnalyzer


@pytest.fixture
def analyzer():
    return IntentAnalyzer()


def test_detect_handoff_keyword(analyzer):
    """检测转人工关键词"""
    result = analyzer.analyze('我要找人工客服')
    assert result.intent == 'handoff'
    assert result.requires_human is True
    assert '人工' in result.reason


def test_detect_complaint(analyzer):
    """检测投诉关键词"""
    result = analyzer.analyze('我要投诉，你们服务太差了')
    assert result.intent == 'handoff'
    assert result.requires_human is True


def test_detect_refund(analyzer):
    """检测退款关键词"""
    result = analyzer.analyze('我想申请退款')
    assert result.intent == 'handoff'
    assert result.requires_human is True


def test_detect_greeting(analyzer):
    """识别问候语"""
    result = analyzer.analyze('你好')
    assert result.intent == 'greeting'
    assert result.requires_human is False


def test_detect_greeting_english(analyzer):
    """识别英文问候"""
    result = analyzer.analyze('Hello, how are you')
    assert result.intent == 'greeting'


def test_detect_thanks(analyzer):
    """识别感谢语"""
    result = analyzer.analyze('非常感谢您的帮助')
    assert result.intent == 'thanks'
    assert result.requires_human is False


def test_default_question(analyzer):
    """默认识别为普通问题"""
    result = analyzer.analyze('你们的营业时间是什么？')
    assert result.intent == 'question'
    assert result.requires_human is False


def test_handoff_precedence_over_greeting(analyzer):
    """转人工优先级高于问候"""
    result = analyzer.analyze('你好，我想退款')
    assert result.intent == 'handoff'


def test_empty_message_returns_question(analyzer):
    """空消息返回普通问题"""
    result = analyzer.analyze('   ')
    assert result.intent == 'question'


def test_whitespace_and_case_insensitive(analyzer):
    """忽略大小写和首尾空格"""
    result = analyzer.analyze('  HELLO  ')
    assert result.intent == 'greeting'
