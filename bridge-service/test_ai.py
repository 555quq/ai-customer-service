#!/usr/bin/env python3
"""
测试AI引擎
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.services.ai_engine import AIEngine
from loguru import logger


async def test_chat():
    """测试对话功能"""
    engine = AIEngine()

    try:
        logger.info("初始化AI引擎...")
        await engine.initialize()

        # 测试问题
        test_questions = [
            "你好",
            "你们的营业时间是什么？",
            "如何退货？",
            "我要投诉",
        ]

        conversation_id = "test-conv-001"

        for i, question in enumerate(test_questions, 1):
            logger.info(f"\n{'='*50}")
            logger.info(f"测试 {i}/{len(test_questions)}: {question}")
            logger.info(f"{'='*50}")

            response = await engine.chat(
                message=question,
                conversation_id=conversation_id
            )

            print(f"\n用户: {question}")
            print(f"AI: {response.reply}")
            print(f"置信度: {response.confidence}")
            print(f"意图: {response.intent}")
            if response.sources:
                print(f"来源: {len(response.sources)} 个参考文档")
                for j, src in enumerate(response.sources[:2], 1):
                    print(f"  参考{j}: {src['text'][:100]}... (相似度: {src['score']:.2f})")
            print()

        logger.info("测试完成！")

    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await engine.close()


if __name__ == "__main__":
    asyncio.run(test_chat())
