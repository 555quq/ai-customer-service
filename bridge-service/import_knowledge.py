#!/usr/bin/env python3
"""
知识库导入脚本
用于初始化向量数据库
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.services.ai_engine import AIEngine
from loguru import logger


async def main():
    """主函数"""
    logger.info("开始导入知识库...")

    try:
        # 初始化AI引擎
        engine = AIEngine()

        # 加载知识库
        await engine.initialize()

        # 显示集合信息
        info = engine.vector_store.get_collection_info()
        logger.info(f"向量库信息: {info}")

        logger.info("知识库导入完成！")

    except Exception as e:
        logger.error(f"导入失败: {e}")
        sys.exit(1)
    finally:
        await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
