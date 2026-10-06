"""意图识别服务"""
from dataclasses import dataclass
from loguru import logger

from ..config import settings


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: str
    requires_human: bool
    reason: str


class IntentAnalyzer:
    """意图识别器（基于规则）"""

    def __init__(self) -> None:
        """初始化意图识别器"""
        self.handoff_keywords = settings.handoff_keywords
        self.greeting_keywords = ['你好', '您好', 'hello', 'hi', '嗨']
        self.thanks_keywords = ['谢谢', '感谢', 'thanks', 'thank you']

    def analyze(self, message: str) -> IntentResult:
        """分析用户消息意图

        Args:
            message: 用户消息文本

        Returns:
            意图识别结果
        """
        message_lower = message.lower().strip()

        # 检测转人工关键词
        for keyword in self.handoff_keywords:
            if keyword in message_lower:
                logger.info(f"检测到转人工关键词: '{keyword}'")
                return IntentResult(
                    intent='handoff',
                    requires_human=True,
                    reason=f"用户提及关键词：{keyword}"
                )

        # 检测问候语
        for keyword in self.greeting_keywords:
            if keyword in message_lower:
                logger.debug("识别为问候语")
                return IntentResult(
                    intent='greeting',
                    requires_human=False,
                    reason='问候语'
                )

        # 检测感谢语
        for keyword in self.thanks_keywords:
            if keyword in message_lower:
                logger.debug("识别为感谢语")
                return IntentResult(
                    intent='thanks',
                    requires_human=False,
                    reason='感谢语'
                )

        # 默认为普通问题
        logger.debug("识别为普通问题")
        return IntentResult(
            intent='question',
            requires_human=False,
            reason='常规咨询'
        )
