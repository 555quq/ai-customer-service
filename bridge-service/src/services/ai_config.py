"""AI服务配置"""
from typing import Optional

from pydantic_settings import BaseSettings


class AIConfig(BaseSettings):
    """AI引擎配置"""

    # OpenAI API配置（支持兼容接口）
    openai_api_key: Optional[str] = None
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-3.5-turbo"

    # 国产大模型配置示例（取消注释使用）
    # DeepSeek
    # openai_api_base: str = "https://api.deepseek.com/v1"
    # openai_model: str = "deepseek-chat"

    # 通义千问
    # openai_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # openai_model: str = "qwen-turbo"

    # Moonshot
    # openai_api_base: str = "https://api.moonshot.cn/v1"
    # openai_model: str = "moonshot-v1-8k"

    # 向量数据库配置
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "customer_service_kb"

    # Embedding 配置（本地 fastembed，免费离线；bge-small-zh 中文专精，512 维）
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_cache_dir: str = "data/model_cache"
    embedding_dimension: int = 512

    # RAG配置
    max_context_length: int = 4000
    top_k_results: int = 3
    similarity_threshold: float = 0.5

    # 系统Prompt
    system_prompt: str = """你是一个专业的客服助手。

你的任务:
1. 根据提供的知识库内容准确回答用户问题
2. 如果知识库中没有相关信息，请诚实告知用户
3. 对于复杂或知识库外的问题，建议用户转人工客服

回答要求:
- 简洁专业，不要过于啰嗦
- 友好礼貌，使用温和的语气
- 如果不确定，不要编造信息
- 适当使用 emoji 让对话更友好 😊"""

    class Config:
        env_file = ".env"
        env_prefix = "AI_"
