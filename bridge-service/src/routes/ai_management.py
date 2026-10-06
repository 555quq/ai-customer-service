"""
AI管理API路由
提供知识库管理、配置管理、测试等接口
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from loguru import logger
import tempfile
import shutil
from pathlib import Path
from uuid import uuid4

from ..config import settings
from ..services.ai_engine import AIEngine
from ..auth.dependencies import require_admin

router = APIRouter(prefix="/api/ai", tags=["AI Management"], dependencies=[Depends(require_admin)])

# 全局AI引擎实例（从main.py注入）
_ai_engine: AIEngine = None


def set_ai_engine(engine: AIEngine):
    """设置AI引擎实例"""
    global _ai_engine
    _ai_engine = engine


# ==================== 数据模型 ====================

class TestChatRequest(BaseModel):
    """测试对话请求"""
    message: str


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    apiKey: str = None
    apiBase: str = None
    model: str = None
    topK: int = None
    similarityThreshold: float = None


# ==================== API端点 ====================

@router.get("/stats")
async def get_ai_stats():
    """
    获取AI引擎统计信息

    Returns:
        AI引擎状态和统计数据
    """
    if not _ai_engine:
        raise HTTPException(status_code=503, detail="AI引擎未初始化")

    try:
        # 获取向量库信息
        collection_info = _ai_engine.vector_store.get_collection_info()

        # 获取配置
        config = _ai_engine.config

        return {
            "totalDocuments": collection_info.get("points_count", 0),
            "modelName": config.openai_model,
            "vectorDBStatus": "healthy" if collection_info else "error",
            "lastUpdated": "最近更新",  # 可以从数据库获取
            "apiBase": config.openai_api_base,
            "topK": config.top_k_results,
            "similarityThreshold": config.similarity_threshold
        }
    except Exception as e:
        logger.error(f"获取AI统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge")
async def get_knowledge_list(
    limit: int = 50,
    offset: int = 0
):
    """
    获取知识库列表

    Args:
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        知识库条目列表
    """
    if not _ai_engine:
        raise HTTPException(status_code=503, detail="AI引擎未初始化")

    try:
        # 从 Qdrant 向量库滚动获取真实知识条目
        return await _ai_engine.vector_store.scroll_documents(limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"获取知识库列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/knowledge/upload")
async def upload_knowledge_file(
    file: UploadFile = File(...)
):
    """
    上传知识库文件

    Args:
        file: 上传的文件（JSON, TXT, MD, PDF, DOCX）

    Returns:
        上传结果
    """
    if not _ai_engine:
        raise HTTPException(status_code=503, detail="AI引擎未初始化")

    # Normalize both POSIX and Windows separators supplied by untrusted clients.
    safe_filename = Path((file.filename or "").replace("\\", "/")).name
    if not safe_filename or safe_filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="文件名无效")

    # 检查文件类型
    allowed_extensions = ['.json', '.txt', '.md', '.markdown', '.pdf', '.docx']
    file_ext = Path(safe_filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}"
        )

    tmp_path = None
    target_path = None
    keep_target = False
    try:
        # Stream to a temporary file while enforcing the configured size limit.
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            tmp_path = Path(tmp.name)
            total_bytes = 0
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > settings.knowledge_upload_max_bytes:
                    raise HTTPException(status_code=413, detail="上传文件超过大小限制")
                tmp.write(chunk)

        # Generate the stored filename server-side and prove it stays in the KB root.
        knowledge_dir = Path(_ai_engine.knowledge_loader.knowledge_dir).resolve()
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        target_path = (knowledge_dir / f"{uuid4().hex}_{safe_filename}").resolve()
        if not target_path.is_relative_to(knowledge_dir):
            raise HTTPException(status_code=400, detail="文件路径无效")

        shutil.copyfile(tmp_path, target_path)

        logger.info(f"文件已保存: {target_path}")

        # 加载新文件
        loader = _ai_engine.knowledge_loader

        if file_ext == '.json':
            documents = loader.load_json(target_path)
        elif file_ext in ['.txt', '.md', '.markdown']:
            documents = loader.load_txt(target_path)
        elif file_ext == '.pdf':
            documents = loader.load_pdf(target_path)
        elif file_ext == '.docx':
            documents = loader.load_docx(target_path)
        else:
            raise HTTPException(status_code=400, detail="不支持的文件类型")

        if not documents:
            raise HTTPException(status_code=400, detail="文件解析失败或内容为空")

        # 向量化并存储
        await _ai_engine._index_documents(documents)
        keep_target = True

        return {
            "success": True,
            "filename": safe_filename,
            "documentsAdded": len(documents),
            "message": f"成功添加 {len(documents)} 个文档到知识库"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传知识库文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        if target_path is not None and not keep_target:
            target_path.unlink(missing_ok=True)


@router.post("/knowledge/reload")
async def reload_knowledge():
    """
    重新加载知识库

    清空现有向量库并重新加载所有文件

    Returns:
        重新加载结果
    """
    if not _ai_engine:
        raise HTTPException(status_code=503, detail="AI引擎未初始化")

    try:
        await _ai_engine.reload_knowledge()

        # 获取新的统计
        collection_info = _ai_engine.vector_store.get_collection_info()

        return {
            "success": True,
            "totalDocuments": collection_info.get("points_count", 0),
            "message": "知识库重新加载成功"
        }
    except Exception as e:
        logger.error(f"重新加载知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test")
async def test_chat(request: TestChatRequest):
    """
    测试AI对话

    Args:
        request: 测试请求

    Returns:
        AI回复和详细信息
    """
    if not _ai_engine:
        raise HTTPException(status_code=503, detail="AI引擎未初始化")

    try:
        response = await _ai_engine.chat(
            message=request.message,
            conversation_id="test-conversation",
            user_id="test-user"
        )

        return {
            "reply": response.reply,
            "confidence": response.confidence,
            "intent": response.intent,
            "sources": response.sources,
            "message": request.message
        }
    except Exception as e:
        logger.error(f"测试对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def update_config(request: ConfigUpdateRequest):
    """
    更新AI引擎配置

    Args:
        request: 配置更新请求

    Returns:
        更新结果
    """
    if not _ai_engine:
        raise HTTPException(status_code=503, detail="AI引擎未初始化")

    try:
        # 更新配置
        config = _ai_engine.config

        if request.apiKey:
            config.openai_api_key = request.apiKey
            _ai_engine.llm.api_key = request.apiKey

        if request.apiBase:
            config.openai_api_base = request.apiBase
            _ai_engine.llm.api_base = request.apiBase

        if request.model:
            config.openai_model = request.model
            _ai_engine.llm.model = request.model

        if request.topK is not None:
            config.top_k_results = request.topK

        if request.similarityThreshold is not None:
            config.similarity_threshold = request.similarityThreshold

        # TODO: 持久化配置到.env文件

        return {
            "success": True,
            "message": "配置更新成功",
            "config": {
                "apiBase": config.openai_api_base,
                "model": config.openai_model,
                "topK": config.top_k_results,
                "similarityThreshold": config.similarity_threshold
            }
        }
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """
    AI引擎健康检查

    Returns:
        健康状态
    """
    if not _ai_engine:
        return {
            "status": "not_initialized",
            "message": "AI引擎未初始化"
        }

    try:
        # 检查向量库连接
        collection_info = _ai_engine.vector_store.get_collection_info()
        vector_db_ok = bool(collection_info)

        # 检查LLM连接（简单检查）
        llm_ok = bool(_ai_engine.llm.api_key)

        return {
            "status": "healthy" if (vector_db_ok and llm_ok) else "degraded",
            "vectorDB": "ok" if vector_db_ok else "error",
            "llm": "ok" if llm_ok else "error",
            "documentsCount": collection_info.get("points_count", 0)
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
