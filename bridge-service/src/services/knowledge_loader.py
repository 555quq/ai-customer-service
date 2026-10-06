"""知识库文件加载器"""
import json
from typing import List, Dict
from pathlib import Path
from loguru import logger

# 文档解析库
try:
    from PyPDF2 import PdfReader
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    logger.warning("未安装PyPDF2，无法解析PDF文件")

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    logger.warning("未安装python-docx，无法解析Word文件")


class KnowledgeLoader:
    """知识库文件加载器"""

    def __init__(self, knowledge_dir: str = "data/knowledge"):
        self.knowledge_dir = Path(knowledge_dir)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    def load_txt(self, file_path: Path) -> List[Dict]:
        """加载TXT文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 按段落分割
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

            documents = []
            for i, para in enumerate(paragraphs):
                if len(para) > 10:  # 过滤太短的段落
                    documents.append({
                        "text": para,
                        "metadata": {
                            "source": file_path.name,
                            "type": "txt",
                            "chunk_id": i
                        }
                    })

            return documents

        except Exception as e:
            logger.error(f"加载TXT文件失败 {file_path}: {e}")
            return []

    def load_md(self, file_path: Path) -> List[Dict]:
        """加载Markdown文件"""
        return self.load_txt(file_path)

    def load_json(self, file_path: Path) -> List[Dict]:
        """
        加载JSON文件

        支持格式:
        [
            {"question": "...", "answer": "..."},
            ...
        ]
        或
        [
            {"text": "...", "category": "..."},
            ...
        ]
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                data = [data]

            documents = []
            for i, item in enumerate(data):
                # 处理 Q&A 格式
                if "question" in item and "answer" in item:
                    text = f"问：{item['question']}\n答：{item['answer']}"
                # 处理纯文本格式
                elif "text" in item:
                    text = item["text"]
                else:
                    # 将整个对象转为文本
                    text = json.dumps(item, ensure_ascii=False)

                documents.append({
                    "text": text,
                    "metadata": {
                        "source": file_path.name,
                        "type": "json",
                        "chunk_id": i,
                        **{k: v for k, v in item.items()
                           if k not in ["text", "question", "answer"]}
                    }
                })

            return documents

        except Exception as e:
            logger.error(f"加载JSON文件失败 {file_path}: {e}")
            return []

    def load_pdf(self, file_path: Path) -> List[Dict]:
        """加载 PDF 文件"""
        if not HAS_PDF:
            logger.warning(f"未安装PyPDF2，跳过PDF: {file_path}")
            return []
        documents = []
        try:
            reader = PdfReader(str(file_path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if text.strip():
                documents.append({
                    "text": text,
                    "metadata": {"source": file_path.name}
                })
        except Exception as e:
            logger.error(f"加载PDF失败 {file_path}: {e}")
        return documents

    def load_docx(self, file_path: Path) -> List[Dict]:
        """加载 Word 文件"""
        if not HAS_DOCX:
            logger.warning(f"未安装python-docx，跳过Word: {file_path}")
            return []
        documents = []
        try:
            doc = Document(str(file_path))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            if text.strip():
                documents.append({
                    "text": text,
                    "metadata": {"source": file_path.name}
                })
        except Exception as e:
            logger.error(f"加载Word失败 {file_path}: {e}")
        return documents

    def load_all(self) -> List[Dict]:
        """加载所有知识库文件"""
        all_documents = []

        # 支持的文件类型
        loaders = {
            '.txt': self.load_txt,
            '.md': self.load_md,
            '.markdown': self.load_md,
            '.json': self.load_json,
            '.pdf': self.load_pdf,
            '.docx': self.load_docx,
        }

        for file_path in self.knowledge_dir.glob('**/*'):
            if file_path.is_file():
                ext = file_path.suffix.lower()
                loader = loaders.get(ext)

                if loader:
                    logger.info(f"加载文件: {file_path}")
                    docs = loader(file_path)
                    all_documents.extend(docs)
                else:
                    logger.warning(f"不支持的文件类型: {file_path}")

        logger.info(f"总共加载 {len(all_documents)} 个文档片段")
        return all_documents

    def save_sample_json(self):
        """创建示例JSON知识库文件"""
        sample_data = [
            {
                "question": "你们的营业时间是什么？",
                "answer": "我们的营业时间是周一至周五 9:00-18:00，周末 10:00-17:00。",
                "category": "基本信息"
            },
            {
                "question": "如何退货？",
                "answer": "购买后30天内，商品未使用且包装完好，可以申请无理由退货。请联系客服提供订单号。",
                "category": "售后服务"
            },
            {
                "question": "支持哪些支付方式？",
                "answer": "我们支持微信支付、支付宝、银行卡支付等多种支付方式。",
                "category": "支付相关"
            },
            {
                "question": "配送需要多久？",
                "answer": "一般情况下，下单后2-3个工作日即可送达。偏远地区可能需要5-7个工作日。",
                "category": "配送信息"
            },
            {
                "question": "忘记密码怎么办？",
                "answer": "点击登录页的'忘记密码'，输入注册邮箱，我们会发送重置密码的链接到您的邮箱。",
                "category": "账户问题"
            }
        ]

        sample_file = self.knowledge_dir / "sample_qa.json"
        with open(sample_file, 'w', encoding='utf-8') as f:
            json.dump(sample_data, f, ensure_ascii=False, indent=2)

        logger.info(f"创建示例知识库文件: {sample_file}")
